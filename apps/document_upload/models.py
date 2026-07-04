"""
apps/document_upload/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Document and DocumentPage - the core upload / pipeline state machine.

Pipeline states (spec: Document Pipeline):
  PENDING -> PROCESSING -> OCR_REQUIRED -> EXTRACTING -> CHUNKING
  -> EMBEDDING -> INDEXED   (happy path)
  -> FAILED                 (any unrecoverable error)

Design decisions:
- SHA-256 hash stored on upload; a unique constraint prevents duplicate
  files being indexed twice (spec: "Generate SHA256 hash. Prevent duplicate uploads").
- file_size, mime_type and extension are captured at upload time so the
  pipeline can route the file without re-reading it.
- DocumentPage stores the per-page text extracted by OCR or the parser;
  this is the raw material fed into chunking.
- processing_error stores the last exception message so admins can diagnose
  failures without digging through logs.
"""

from django.db import models
from core.models import BaseModel
from apps.knowledge_base.models import KnowledgeBase, Tag


class Document(BaseModel):
    """One uploaded source file, regardless of type."""

    class Status(models.TextChoices):
        PENDING       = "pending",       "Pending"
        PROCESSING    = "processing",    "Processing"
        OCR_REQUIRED  = "ocr_required",  "OCR Required"
        EXTRACTING    = "extracting",    "Extracting Text"
        CHUNKING      = "chunking",      "Chunking"
        EMBEDDING     = "embedding",     "Generating Embeddings"
        INDEXED       = "indexed",       "Indexed"
        FAILED        = "failed",        "Failed"

    class FileCategory(models.TextChoices):
        PDF       = "pdf",       "PDF"
        WORD      = "word",      "Word Document"
        EXCEL     = "excel",     "Excel Spreadsheet"
        CSV       = "csv",       "CSV"
        TEXT      = "text",      "Plain Text"
        HTML      = "html",      "HTML"
        RTF       = "rtf",       "RTF"
        PPTX      = "pptx",      "PowerPoint"
        IMAGE     = "image",     "Image"
        ARCHIVE   = "archive",   "ZIP Archive"
        UNKNOWN   = "unknown",   "Unknown"

    # -- Identification -----------------------------------------------------
    title = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=500)
    file = models.FileField(upload_to="documents/originals/%Y/%m/")
    file_size = models.PositiveBigIntegerField(help_text="Size in bytes")
    mime_type = models.CharField(max_length=200, blank=True)
    extension = models.CharField(max_length=20, blank=True, db_index=True)
    file_category = models.CharField(
        max_length=20,
        choices=FileCategory.choices,
        default=FileCategory.UNKNOWN,
        db_index=True,
    )
    # Duplicate-detection (spec: "Generate SHA256 hash. Prevent duplicate uploads")
    sha256_hash = models.CharField(max_length=64, unique=True, db_index=True)

    # -- Organisation -------------------------------------------------------
    knowledge_base = models.ForeignKey(
        KnowledgeBase,
        on_delete=models.PROTECT,
        related_name="documents",
        db_index=True,
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")

    # -- Pipeline state machine ---------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    # -- Extracted metadata (populated by parsers/OCR) ----------------------
    page_count = models.PositiveIntegerField(default=0)
    word_count = models.PositiveIntegerField(default=0)
    language = models.CharField(max_length=10, blank=True)
    author = models.CharField(max_length=255, blank=True)
    doc_created_at = models.DateTimeField(null=True, blank=True)  # from file metadata
    doc_modified_at = models.DateTimeField(null=True, blank=True)

    # -- OCR flag ----------------------------------------------------------
    requires_ocr = models.BooleanField(default=False)
    ocr_completed = models.BooleanField(default=False)

    # -- Parent (for files extracted from a ZIP archive) -------------------
    parent_document = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="extracted_documents",
    )

    class Meta:
        db_table = "doc_document"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "is_deleted"], name="idx_doc_status"),
            models.Index(fields=["knowledge_base", "status"], name="idx_doc_kb_status"),
            models.Index(fields=["sha256_hash"], name="idx_doc_hash"),
            models.Index(fields=["file_category"], name="idx_doc_category"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["sha256_hash"],
                condition=models.Q(is_deleted=False),
                name="uq_doc_hash_active",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} [{self.get_status_display()}]"

    @property
    def is_indexed(self) -> bool:
        return self.status == self.Status.INDEXED

    @property
    def failed(self) -> bool:
        return self.status == self.Status.FAILED


class DocumentPage(BaseModel):
    """
    Stores the raw extracted text for each page of a document.
    For non-paginated formats (CSV, TXT) there will be a single page (page_number=1).
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="pages",
        db_index=True,
    )
    page_number = models.PositiveIntegerField()
    raw_text = models.TextField(blank=True)
    # True if this page's text came from Tesseract rather than the parser
    is_ocr = models.BooleanField(default=False)
    ocr_confidence = models.FloatField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "doc_document_page"
        ordering = ["document", "page_number"]
        indexes = [
            models.Index(fields=["document", "page_number"], name="idx_page_doc_num"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "page_number"],
                name="uq_page_doc_num",
            )
        ]

    def __str__(self) -> str:
        return f"Page {self.page_number} of {self.document_id}"
