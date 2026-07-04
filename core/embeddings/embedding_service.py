"""
core/embeddings/embedding_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EmbeddingService — orchestrates chunking → embedding → vector-store indexing.

Called from:
  1. DocumentPipelineService._process_file() after pages are saved (Phase 5 hook)
  2. Management command: python manage.py reindex_document <pk>
  3. Background django-q2 task (Phase 8)

Spec checklist:
  ✓ Configurable chunk size + overlap (from PlatformSetting)
  ✓ Admin-selectable chunking strategy
  ✓ Batch embedding generation
  ✓ Incremental indexing (skip already-embedded chunks)
  ✓ Store: vector, chunk text, source file, page, paragraph, chunk ID, created date
"""

import logging
import time
from typing import Optional

from django.conf import settings
from django.utils import timezone

from apps.document_upload.models import Document
from apps.embedding_service.models import DocumentChunk, EmbeddingRecord
from core.ai.ollama_client import OllamaClient, OllamaError
from .chunkers import ChunkerFactory, ChunkResult
from .token_utils import count_tokens
from .vector_store import VectorStoreFactory, VectorStoreBase

logger = logging.getLogger(__name__)

# Batch size for embedding calls — keeps Ollama memory stable
EMBED_BATCH_SIZE = 16


def _get_active_embedding_model() -> str:
    """
    Read the active embedding model name from AIModel or fall back
    to settings.DEFAULT_EMBEDDING_MODEL.
    """
    try:
        from apps.ai_agent.models import AIModel
        model = AIModel.objects.filter(
            model_type=AIModel.ModelType.EMBEDDING,
            is_active=True,
            is_default=True,
        ).first()
        if model:
            return model.name
    except Exception:
        pass
    return getattr(settings, "DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")


def _get_chunking_config() -> tuple[str, int, int]:
    """
    Returns (strategy, chunk_size, overlap) from PlatformSetting,
    falling back to Django settings defaults.
    """
    strategy   = getattr(settings, "DEFAULT_CHUNKING_STRATEGY",   "recursive")
    chunk_size = getattr(settings, "DEFAULT_CHUNK_SIZE_TOKENS",   1024)
    overlap    = getattr(settings, "DEFAULT_CHUNK_OVERLAP_TOKENS", 150)
    try:
        from apps.settings_app.models import PlatformSetting
        get = lambda key, default: PlatformSetting.objects.filter(
            key=key
        ).first()
        s = get("chunking.strategy",       None)
        c = get("chunking.chunk_size",     None)
        o = get("chunking.overlap_tokens", None)
        if s: strategy   = s.typed_value()
        if c: chunk_size = int(c.typed_value())
        if o: overlap    = int(o.typed_value())
    except Exception:
        pass
    return strategy, chunk_size, overlap


class EmbeddingService:

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        vector_store: Optional[VectorStoreBase] = None,
    ):
        self._ollama = ollama_client or OllamaClient()
        self._store  = vector_store  # lazy: resolved on first use

    def _get_store(self) -> VectorStoreBase:
        if self._store is None:
            self._store = VectorStoreFactory.get()
        return self._store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_document(self, document: Document, force: bool = False) -> dict:
        """
        Chunk + embed + index one document.
        Returns a summary dict: {chunks_created, chunks_embedded, elapsed_s, error}.

        If force=False, already-embedded chunks are skipped (incremental indexing).
        """
        start = time.perf_counter()
        summary = {"chunks_created": 0, "chunks_embedded": 0, "elapsed_s": 0.0, "error": ""}

        try:
            strategy, chunk_size, overlap = _get_chunking_config()
            model_name = _get_active_embedding_model()

            logger.info(
                "Indexing document #%d '%s' | strategy=%s size=%d overlap=%d model=%s",
                document.pk, document.title, strategy, chunk_size, overlap, model_name,
            )

            # --- Stage: Chunking ----------------------------------------
            document.status = Document.Status.CHUNKING
            document.save(update_fields=["status"])

            chunks = self._chunk_document(document, strategy, chunk_size, overlap)
            summary["chunks_created"] = len(chunks)

            if not chunks:
                logger.warning("Document #%d produced zero chunks.", document.pk)
                document.status = Document.Status.INDEXED
                document.save(update_fields=["status"])
                return summary

            # --- Stage: Embedding ----------------------------------------
            document.status = Document.Status.EMBEDDING
            document.save(update_fields=["status"])

            embedded = self._embed_and_store(
                document, chunks, model_name, force=force
            )
            summary["chunks_embedded"] = embedded

            # --- Done -------------------------------------------------------
            document.status = Document.Status.INDEXED
            document.processing_completed_at = timezone.now()
            document.save(update_fields=["status", "processing_completed_at"])

            summary["elapsed_s"] = round(time.perf_counter() - start, 2)
            logger.info(
                "Document #%d indexed: %d chunks, %d embedded, %.2fs",
                document.pk, len(chunks), embedded, summary["elapsed_s"],
            )

        except OllamaError as e:
            msg = f"Ollama unreachable: {e}"
            logger.error("Embedding failed for document #%d: %s", document.pk, msg)
            document.status = Document.Status.FAILED
            document.processing_error = msg
            document.save(update_fields=["status", "processing_error"])
            summary["error"] = msg

        except Exception as e:
            logger.exception("Unexpected embedding error for document #%d", document.pk)
            document.status = Document.Status.FAILED
            document.processing_error = str(e)
            document.save(update_fields=["status", "processing_error"])
            summary["error"] = str(e)

        return summary

    def index_pending(self, limit: int = 50) -> list[dict]:
        """Index all documents that are in CHUNKING status."""
        docs = Document.objects.filter(
            status=Document.Status.CHUNKING, is_deleted=False
        ).order_by("created_at")[:limit]
        return [self.index_document(doc) for doc in docs]

    def delete_document_vectors(self, document: Document) -> None:
        """Remove all vectors for a document from the vector store."""
        try:
            self._get_store().delete_by_document(document.pk)
            DocumentChunk.objects.filter(document=document).delete()
            logger.info("Deleted vectors for document #%d", document.pk)
        except Exception as e:
            logger.error("Vector delete failed for doc #%d: %s", document.pk, e)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _chunk_document(
        self,
        document: Document,
        strategy: str,
        chunk_size: int,
        overlap: int,
    ) -> list[DocumentChunk]:
        """
        Read DocumentPage rows, run the chunker, and persist DocumentChunk rows.
        Returns the list of saved DocumentChunk objects.
        """
        chunker = ChunkerFactory.get(strategy, chunk_size, overlap)
        pages   = list(document.pages.order_by("page_number"))

        if not pages:
            logger.warning("Document #%d has no pages — nothing to chunk.", document.pk)
            return []

        # Delete stale chunks from any previous run
        DocumentChunk.objects.filter(document=document).delete()

        all_chunk_results: list[ChunkResult] = []
        global_index = 0

        for page in pages:
            if not page.raw_text.strip():
                continue
            page_chunks = chunker.chunk(
                text=page.raw_text,
                page_number=page.page_number,
                start_index=global_index,
            )
            all_chunk_results.extend(page_chunks)
            global_index += len(page_chunks)

        # Bulk-create DocumentChunk rows
        to_create = []
        for cr in all_chunk_results:
            to_create.append(DocumentChunk(
                document=document,
                chunk_index=cr.chunk_index,
                text=cr.text,
                token_count=cr.token_count,
                page_number=cr.page_number,
                paragraph_number=cr.paragraph_number,
                start_char=cr.start_char or 0,
                end_char=cr.end_char or 0,
                strategy_used=strategy,
                chunk_size_setting=chunk_size,
                overlap_setting=overlap,
                is_embedded=False,
                created_by=document.created_by,
                modified_by=document.modified_by,
            ))

        created = DocumentChunk.objects.bulk_create(to_create, batch_size=200)
        logger.info("Document #%d: created %d chunks.", document.pk, len(created))
        return created

    def _embed_and_store(
        self,
        document: Document,
        chunks: list[DocumentChunk],
        model_name: str,
        force: bool = False,
    ) -> int:
        """
        Generate embeddings for chunks (skipping already-embedded ones unless force=True)
        and upsert into the vector store.
        Returns count of newly embedded chunks.
        """
        store = self._get_store()

        # Filter chunks that need embedding
        if force:
            to_embed = chunks
        else:
            embedded_ids = set(
                EmbeddingRecord.objects.filter(
                    chunk__in=chunks
                ).values_list("chunk_id", flat=True)
            )
            to_embed = [c for c in chunks if c.pk not in embedded_ids]

        if not to_embed:
            logger.info("Document #%d: all chunks already embedded.", document.pk)
            return 0

        texts = [c.text for c in to_embed]
        embedded_count = 0

        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch_chunks = to_embed[i : i + EMBED_BATCH_SIZE]
            batch_texts  = texts[i : i + EMBED_BATCH_SIZE]

            t0 = time.perf_counter()
            try:
                vectors = self._ollama.embed_batch(batch_texts, model=model_name)
            except OllamaError:
                raise
            elapsed_ms = (time.perf_counter() - t0) * 1000

            dims = len(vectors[0]) if vectors else 0

            # Upsert into vector store
            store_items = []
            for chunk, vector in zip(batch_chunks, vectors):
                vector_id = str(chunk.chunk_id)
                store_items.append((
                    vector_id,
                    vector,
                    {
                        "document_id":    document.pk,
                        "chunk_id":       str(chunk.chunk_id),
                        "chunk_index":    chunk.chunk_index,
                        "page_number":    chunk.page_number or 0,
                        "kb_id":          document.knowledge_base_id,
                        "title":          document.title[:200],
                        "source_file":    document.original_filename[:200],
                    },
                ))
            store.add_batch(store_items)

            # Persist EmbeddingRecord rows
            records = []
            for chunk, vector in zip(batch_chunks, vectors):
                records.append(EmbeddingRecord(
                    chunk=chunk,
                    vector_id=str(chunk.chunk_id),
                    model_name=model_name,
                    vector_dimensions=dims,
                    generation_time_ms=round(elapsed_ms / len(batch_chunks), 2),
                    vector_preview=vector[:8],   # first 8 dims for debugging
                    created_by=document.created_by,
                    modified_by=document.modified_by,
                ))

            EmbeddingRecord.objects.bulk_create(
                records,
                update_conflicts=True,
                update_fields=["model_name", "vector_dimensions", "generation_time_ms", "vector_preview"],
                unique_fields=["chunk"],
                batch_size=200,
            )

            # Mark chunks as embedded
            DocumentChunk.objects.filter(
                pk__in=[c.pk for c in batch_chunks]
            ).update(is_embedded=True)

            embedded_count += len(batch_chunks)
            logger.debug(
                "Embedded batch %d-%d/%d (%.0fms total)",
                i + 1, i + len(batch_chunks), len(to_embed), elapsed_ms,
            )

        return embedded_count


# Module-level singleton
embedding_service = EmbeddingService()
