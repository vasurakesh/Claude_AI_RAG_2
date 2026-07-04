"""
core/agents/retriever.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
RetrievalService — converts a user question into a query embedding,
searches the vector store, hydrates DocumentChunk rows from the DB,
and logs the SearchQuery + SearchResult records for analytics.

Spec checklist:
  ✓ Generate query embedding
  ✓ Similarity search in vector database
  ✓ Retrieve Top-K chunks
  ✓ Re-rank results (optional, controlled by AgentConfig)
  ✓ Log every search for analytics / retrieval quality evaluation
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from django.contrib.auth.models import User

from apps.embedding_service.models import DocumentChunk
from apps.vector_search.models import SearchQuery, SearchResult
from core.ai.ollama_client import OllamaClient, OllamaError
from core.embeddings.vector_store import VectorStoreFactory, SearchHit
from core.prompts import loader as prompt_loader

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A DocumentChunk enriched with its retrieval scores."""
    chunk: DocumentChunk
    similarity_score: float
    rerank_score: Optional[float] = None
    rank: int = 0

    @property
    def final_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.similarity_score

    @property
    def document(self):
        return self.chunk.document

    @property
    def citation_label(self) -> str:
        page = self.chunk.page_number or "?"
        para = self.chunk.paragraph_number or "?"
        return f"[Source: {self.document.title}, Page {page}, Para {para}]"


@dataclass
class RetrievalResult:
    query_text: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    embedding_time_ms: float = 0.0
    search_time_ms: float = 0.0
    rerank_time_ms: float = 0.0
    search_query_id: Optional[int] = None

    @property
    def has_results(self) -> bool:
        return bool(self.chunks)

    @property
    def context_text(self) -> str:
        """Assemble the numbered context block sent to the LLM."""
        parts = []
        for i, rc in enumerate(self.chunks, 1):
            parts.append(
                f"[{i}] {rc.citation_label}\n{rc.chunk.text.strip()}"
            )
        return "\n\n---\n\n".join(parts)


class RetrievalService:

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
    ):
        self._ollama = ollama_client or OllamaClient()

    def _get_embedding_model(self) -> str:
        try:
            from apps.ai_agent.models import AgentConfig
            cfg = AgentConfig.objects.filter(is_active=True).first()
            if cfg and cfg.embedding_model:
                return cfg.embedding_model.name
        except Exception:
            pass
        from django.conf import settings
        return getattr(settings, "DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")

    def _get_agent_config(self):
        try:
            from apps.ai_agent.models import AgentConfig
            return AgentConfig.objects.filter(is_active=True).first()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        knowledge_base_id: Optional[int] = None,
        similarity_threshold: float = 0.0,
        enable_reranking: bool = False,
        user: Optional[User] = None,
    ) -> RetrievalResult:
        """
        Full retrieval pipeline:
          embed query → vector search → hydrate DB chunks → optional rerank → log
        """
        cfg = self._get_agent_config()
        if cfg:
            top_k               = cfg.top_k
            similarity_threshold = cfg.similarity_threshold
            enable_reranking    = cfg.enable_reranking

        result = RetrievalResult(query_text=query)
        embedding_model = self._get_embedding_model()

        # --- 1. Embed query -----------------------------------------------
        t0 = time.perf_counter()
        try:
            query_vector = self._ollama.embed(query, model=embedding_model)
        except OllamaError as e:
            logger.error("Query embedding failed: %s", e)
            raise
        result.embedding_time_ms = (time.perf_counter() - t0) * 1000

        # --- 2. Vector search ---------------------------------------------
        t1 = time.perf_counter()
        store = VectorStoreFactory.get()
        where = None
        if knowledge_base_id:
            where = {"kb_id": str(knowledge_base_id)}

        hits: list[SearchHit] = store.search(
            query_vector=query_vector,
            top_k=top_k * 3,   # over-fetch for threshold + rerank filtering
            where=where,
        )
        result.search_time_ms = (time.perf_counter() - t1) * 1000

        # --- 3. Threshold filter ------------------------------------------
        hits = [h for h in hits if h.score >= similarity_threshold]
        if not hits:
            logger.info("No results above threshold %.3f for query: %s", similarity_threshold, query[:60])
            self._log_search(result, embedding_model, knowledge_base_id, user)
            return result

        # --- 4. Hydrate DocumentChunk objects from DB ---------------------
        chunk_uuid_map: dict[str, SearchHit] = {h.chunk_id: h for h in hits}
        db_chunks = list(
            DocumentChunk.objects.filter(
                chunk_id__in=list(chunk_uuid_map.keys()),
                is_deleted=False,
            ).select_related("document", "document__knowledge_base")
        )

        # Preserve vector-score ordering
        uuid_to_chunk = {str(c.chunk_id): c for c in db_chunks}
        retrieved: list[RetrievedChunk] = []
        for rank, hit in enumerate(hits[:top_k * 2], 1):
            chunk = uuid_to_chunk.get(hit.chunk_id)
            if chunk is None:
                continue
            retrieved.append(RetrievedChunk(
                chunk=chunk,
                similarity_score=hit.score,
                rank=rank,
            ))

        # --- 5. Optional re-ranking ---------------------------------------
        if enable_reranking and retrieved:
            t2 = time.perf_counter()
            retrieved = self._rerank(query, retrieved)
            result.rerank_time_ms = (time.perf_counter() - t2) * 1000

        # Sort by final score, take top_k
        retrieved.sort(key=lambda x: x.final_score, reverse=True)
        retrieved = retrieved[:top_k]
        for i, rc in enumerate(retrieved, 1):
            rc.rank = i

        result.chunks = retrieved

        # --- 6. Log search ------------------------------------------------
        sq = self._log_search(result, embedding_model, knowledge_base_id, user)
        if sq:
            result.search_query_id = sq.pk

        logger.info(
            "Retrieval: '%s' → %d chunks (embed=%.0fms search=%.0fms rerank=%.0fms)",
            query[:60], len(retrieved),
            result.embedding_time_ms, result.search_time_ms, result.rerank_time_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Re-ranking via LLM relevance scoring
    # ------------------------------------------------------------------

    def _rerank(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """
        Ask the LLM to score each passage's relevance to the query (0-1).
        Falls back to original similarity ordering on any error.
        """
        try:
            for rc in chunks:
                prompt = prompt_loader.render(
                    "rerank",
                    question=query,
                    passage=rc.chunk.text[:800],
                )
                resp = self._ollama.generate(prompt=prompt, max_tokens=10, temperature=0.0)
                raw = (resp.get("response") or "").strip()
                try:
                    rc.rerank_score = max(0.0, min(1.0, float(raw)))
                except ValueError:
                    rc.rerank_score = rc.similarity_score
        except Exception as e:
            logger.warning("Re-ranking failed, using similarity order: %s", e)
        return chunks

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_search(
        self,
        result: RetrievalResult,
        embedding_model: str,
        knowledge_base_id: Optional[int],
        user: Optional[User],
    ) -> Optional[SearchQuery]:
        try:
            sq = SearchQuery.objects.create(
                user=user,
                query_text=result.query_text,
                query_embedding_model=embedding_model,
                top_k=len(result.chunks),
                embedding_time_ms=result.embedding_time_ms,
                search_time_ms=result.search_time_ms,
                total_results=len(result.chunks),
                knowledge_base_id=knowledge_base_id,
            )
            if result.chunks:
                SearchResult.objects.bulk_create([
                    SearchResult(
                        query=sq,
                        chunk=rc.chunk,
                        rank=rc.rank,
                        similarity_score=rc.similarity_score,
                        rerank_score=rc.rerank_score,
                        used_in_context=True,
                    )
                    for rc in result.chunks
                ])
            return sq
        except Exception as e:
            logger.warning("Search logging failed: %s", e)
            return None
