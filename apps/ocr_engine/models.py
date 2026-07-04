"""
apps/ocr_engine/models.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
OCR job tracking. One OCRJob per Document page batch.
Separates OCR work-log from the Document model so the document table
stays lean and OCR history is independently queryable.
"""

from django.db import models
from core.models import BaseModel
from apps.document_upload.models import Document


class OCRJob(BaseModel):
    """Tracks a complete OCR run for one document."""

    class Status(models.TextChoices):
        QUEUED     = "queued",     "Queued"
        RUNNING    = "running",    "Running"
        COMPLETED  = "completed",  "Completed"
        FAILED     = "failed",     "Failed"

    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name="ocr_job",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    engine = models.CharField(max_length=50, default="tesseract")
    engine_version = models.CharField(max_length=50, blank=True)
    language = models.CharField(max_length=20, default="eng")

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    pages_processed = models.PositiveIntegerField(default=0)
    pages_failed = models.PositiveIntegerField(default=0)
    average_confidence = models.FloatField(null=True, blank=True)

    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "ocr_job"
        indexes = [
            models.Index(fields=["status"], name="idx_ocr_status"),
        ]

    def __str__(self) -> str:
        return f"OCRJob({self.document_id}) [{self.status}]"


class OCRPageResult(BaseModel):
    """Per-page OCR output, linked to the job for diagnostic queries."""
    job = models.ForeignKey(
        OCRJob,
        on_delete=models.CASCADE,
        related_name="page_results",
    )
    page_number = models.PositiveIntegerField()
    extracted_text = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "ocr_page_result"
        ordering = ["job", "page_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "page_number"],
                name="uq_ocr_page_result",
            )
        ]

    def __str__(self) -> str:
        return f"OCRPage({self.job_id}, p{self.page_number})"
