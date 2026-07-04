"""
core/agents/context_builder.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ContextBuilder — assembles the final context string sent to the LLM.

Responsibilities:
  - Token-budget management: fits as many chunks as possible within
    max_context_tokens, dropping lower-ranked chunks first.
  - Deduplication: removes near-duplicate passages (same document,
    adjacent chunks) that inflate the context without adding information.
  - Source map: builds the citation list attached to every answer.
  - Context validation: asks the LLM whether the retrieved context is
    actually relevant before generating a full answer (hallucination guard).
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from core.embeddings.token_utils import count_tokens
from core.prompts import loader as prompt_loader
from .retriever import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class ContextSource:
    """One citable source in the assembled context."""
    rank: int
    document_title: str
    original_filename: str
    page_number: Optional[int]
    paragraph_number: Optional[int]
    similarity_score: float
    rerank_score: Optional[float]
    chunk_text_preview: str   # first 200 chars for the UI panel

    @property
    def display_score(self) -> float:
        return round(
            self.rerank_score if self.rerank_score is not None else self.similarity_score,
            3,
        )


@dataclass
class BuiltContext:
    context_text: str
    sources: list[ContextSource] = field(default_factory=list)
    token_count: int = 0
    chunks_used: int = 0
    chunks_dropped: int = 0
    is_relevant: bool = True   # False when relevance check says NO


class ContextBuilder:

    def __init__(
        self,
        max_context_tokens: int = 3000,
        dedup_threshold: float = 0.92,
    ):
        self.max_context_tokens = max_context_tokens
        self.dedup_threshold = dedup_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        retrieved_chunks: list[RetrievedChunk],
        validate_relevance: bool = False,
        question: str = "",
        ollama_client=None,
    ) -> BuiltContext:
        """
        Build a token-bounded, deduplicated context from retrieved chunks.
        Optionally validates relevance via a fast LLM call.
        """
        cfg = self._get_agent_config()
        if cfg:
            self.max_context_tokens = cfg.max_context_tokens

        if not retrieved_chunks:
            return BuiltContext(
                context_text="",
                is_relevant=False,
            )

        # --- Deduplication -------------------------------------------
        deduplicated = self._deduplicate(retrieved_chunks)
        dropped_dedup = len(retrieved_chunks) - len(deduplicated)

        # --- Token-budget fitting ------------------------------------
        fitted, dropped_budget = self._fit_to_budget(deduplicated)
        total_dropped = dropped_dedup + dropped_budget

        if not fitted:
            return BuiltContext(context_text="", is_relevant=False)

        # --- Assemble context text -----------------------------------
        parts = []
        sources = []
        for i, rc in enumerate(fitted, 1):
            citation = (
                f"[{i}] Source: {rc.document.title}"
                f" | Page {rc.chunk.page_number or '?'}"
                f" | Para {rc.chunk.paragraph_number or '?'}"
                f" | Score {rc.final_score:.3f}"
            )
            parts.append(f"{citation}\n{rc.chunk.text.strip()}")
            sources.append(ContextSource(
                rank=i,
                document_title=rc.document.title,
                original_filename=rc.document.original_filename,
                page_number=rc.chunk.page_number,
                paragraph_number=rc.chunk.paragraph_number,
                similarity_score=rc.similarity_score,
                rerank_score=rc.rerank_score,
                chunk_text_preview=rc.chunk.text[:200],
            ))

        context_text = "\n\n---\n\n".join(parts)
        token_count = count_tokens(context_text)

        result = BuiltContext(
            context_text=context_text,
            sources=sources,
            token_count=token_count,
            chunks_used=len(fitted),
            chunks_dropped=total_dropped,
            is_relevant=True,
        )

        # --- Optional relevance validation ---------------------------
        if validate_relevance and question and ollama_client:
            result.is_relevant = self._check_relevance(
                question, context_text, ollama_client
            )
            if not result.is_relevant:
                logger.info(
                    "Context relevance check: FAILED for question '%s'", question[:60]
                )

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _deduplicate(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """
        Remove chunks from the same document that share the same page AND
        have overlapping text (adjacent chunks from the same chunker run).
        Keeps the higher-scored one.
        """
        seen: list[RetrievedChunk] = []
        for rc in chunks:
            duplicate = False
            for existing in seen:
                if (
                    existing.chunk.document_id == rc.chunk.document_id
                    and existing.chunk.page_number == rc.chunk.page_number
                    and abs(existing.chunk.chunk_index - rc.chunk.chunk_index) <= 1
                ):
                    duplicate = True
                    break
            if not duplicate:
                seen.append(rc)
        return seen

    def _fit_to_budget(
        self, chunks: list[RetrievedChunk]
    ) -> tuple[list[RetrievedChunk], int]:
        """
        Greedily add chunks (highest score first) until token budget is hit.
        Returns (fitted_chunks, dropped_count).
        """
        fitted = []
        used_tokens = 0
        dropped = 0
        for rc in chunks:
            chunk_tokens = count_tokens(rc.chunk.text)
            separator_tokens = 10   # "---" + citation line overhead
            if used_tokens + chunk_tokens + separator_tokens > self.max_context_tokens:
                dropped += 1
            else:
                fitted.append(rc)
                used_tokens += chunk_tokens + separator_tokens
        return fitted, dropped

    def _check_relevance(
        self, question: str, context_text: str, ollama_client
    ) -> bool:
        """
        Ask the LLM whether the context is relevant to the question.
        Returns True (relevant) or False (not relevant / LLM call failed).
        """
        try:
            prompt = prompt_loader.render(
                "rerank",   # reuses the relevance-check template
                question=question,
                passage=context_text[:1500],
            )
            resp = ollama_client.generate(
                prompt=prompt, max_tokens=5, temperature=0.0
            )
            answer = (resp.get("response") or "").strip().upper()
            return answer.startswith("Y") or answer.startswith("1")
        except Exception as e:
            logger.warning("Relevance check failed: %s — assuming relevant", e)
            return True

    def _get_agent_config(self):
        try:
            from apps.ai_agent.models import AgentConfig
            return AgentConfig.objects.filter(is_active=True).first()
        except Exception:
            return None
