"""
apps/embedding_service/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DocumentChunk and EmbeddingRecord.

Design decisions:
- DocumentChunk holds the text slice + positional metadata needed by the RAG
  context-builder (page, paragraph, chunk index, token count).
- EmbeddingRecord stores the embedding vector as a JSON-serialised list of
  floats. SQLite has no native vector column type; the actual ANN index lives
  in the vector_store/ directory (ChromaDB / FAISS). The DB record is the
  source-of-truth for the chunk<->vector-id mapping and lets us re-index
  without re-chunking.
- chunk_id is a deterministic UUID derived from (document_id, chunk_index) so
  we can safely upsert during re-indexing.
"""

import uuid
from django.db import models
from core.models import BaseModel
from apps.document_upload.models import Document


class DocumentChunk(BaseModel):
    """One text chunk produced by the chunking service."""

    class ChunkStrategy(models.TextChoices):
        PARAGRAPH = "paragraph", "Paragraph"
        SENTENCE  = "sentence",  "Sentence"
        RECURSIVE = "recursive", "Recursive"
        SEMANTIC  = "semantic",  "Semantic"

    # Stable identifier used as the vector-store ID
    chunk_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
        db_index=True,
    )
    chunk_index = models.PositiveIntegerField(
        help_text="Sequential position of this chunk within the document"
    )

    # -- Text content -------------------------------------------------------
    text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)

    # -- Positional metadata (spec: "Store Page Number, Paragraph Number") --
    page_number = models.PositiveIntegerField(null=True, blank=True)
    paragraph_number = models.PositiveIntegerField(null=True, blank=True)
    start_char = models.PositiveIntegerField(null=True, blank=True)
    end_char = models.PositiveIntegerField(null=True, blank=True)

    # -- Chunking provenance ------------------------------------------------
    strategy_used = models.CharField(
        max_length=20,
        choices=ChunkStrategy.choices,
        default=ChunkStrategy.RECURSIVE,
    )
    chunk_size_setting = models.PositiveIntegerField(default=1024)
    overlap_setting = models.PositiveIntegerField(default=150)

    # -- Embedding status ---------------------------------------------------
    is_embedded = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "emb_document_chunk"
        ordering = ["document", "chunk_index"]
        indexes = [
            models.Index(fields=["document", "chunk_index"], name="idx_chunk_doc_idx"),
            models.Index(fields=["is_embedded"], name="idx_chunk_embedded"),
            models.Index(fields=["chunk_id"], name="idx_chunk_uuid"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="uq_chunk_doc_index",
            )
        ]

    def __str__(self) -> str:
        return f"Chunk({self.document_id}, #{self.chunk_index})"


class EmbeddingRecord(BaseModel):
    """
    Metadata for the embedding vector stored in the vector database.
    The actual float array is NOT stored here (kept in ChromaDB/FAISS to
    allow GPU-accelerated ANN search). This table tracks which model
    generated the vector and lets us invalidate/re-embed efficiently.
    """
    chunk = models.OneToOneField(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="embedding",
    )
    # ID used in the vector store (matches chunk.chunk_id for ChromaDB)
    vector_id = models.CharField(max_length=100, unique=True, db_index=True)
    model_name = models.CharField(max_length=200)
    model_version = models.CharField(max_length=100, blank=True)
    vector_dimensions = models.PositiveSmallIntegerField()

    # Generation performance telemetry
    generation_time_ms = models.FloatField(null=True, blank=True)
    # Stored only for debugging / drift-detection; kept null in production
    # to avoid ballooning the SQLite file.
    vector_preview = models.JSONField(
        null=True,
        blank=True,
        help_text="First 8 dimensions of the vector, for sanity checks",
    )

    class Meta:
        db_table = "emb_embedding_record"
        indexes = [
            models.Index(fields=["model_name"], name="idx_emb_model"),
            models.Index(fields=["vector_id"], name="idx_emb_vector_id"),
        ]

    def __str__(self) -> str:
        return f"Embedding({self.chunk_id}) [{self.model_name}]"
