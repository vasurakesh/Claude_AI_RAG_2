"""
core/services/document_pipeline.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DocumentPipelineService — orchestrates the full document processing pipeline.

Pipeline stages (spec: Document Pipeline):
  1. Store original file
  2. Generate SHA-256 hash + duplicate check
  3. Extract text (parser)  OR  flag for OCR
  4. If OCR required → TesseractEngine
  5. Normalize Unicode / remove headers-footers / collapse whitespace
  6. Extract metadata (title, author, dates, page count, word count)
  7. Persist DocumentPage rows
  8. Advance Document.status  (→ INDEXED after chunking in Phase 5)

ZIP archives are expanded here:
  - Every file inside the ZIP is extracted to a temp folder
  - Each file is processed recursively through the same pipeline
  - Extracted Document rows reference the ZIP Document via parent_document

This service is intentionally synchronous so it can be called either:
  a) directly from a view (small files), or
  b) from a django-q2 background task (Phase 8)
"""

import io
import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.document_upload.models import Document, DocumentPage
from apps.ocr_engine.models import OCRJob, OCRPageResult
from core.services.parsers import DocumentParser, ParseResult
from core.ocr.tesseract_engine import TesseractEngine
from core.utilities.file_utils import (
    sha256_of_file, sha256_of_bytes, get_extension,
    get_file_category, is_allowed_extension, safe_filename,
)
from core.utilities.text_utils import normalize_text, count_words

logger = logging.getLogger(__name__)

_parser   = DocumentParser()
_ocr      = TesseractEngine()


class DuplicateDocumentError(Exception):
    """Raised when an uploaded file's SHA-256 hash already exists in the DB."""
    def __init__(self, existing_doc: Document):
        self.existing_doc = existing_doc
        super().__init__(f"Duplicate of document #{existing_doc.pk}: {existing_doc.title}")


class UnsupportedFileTypeError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DocumentPipelineService:

    def ingest(
        self,
        file_obj,
        filename: str,
        knowledge_base,
        uploaded_by,
        parent_document: Optional[Document] = None,
    ) -> Document:
        """
        Full ingest pipeline for one file.
        Returns the saved Document instance (status=INDEXED if all goes well,
        or status=FAILED on unrecoverable error).
        """
        ext = get_extension(filename)
        if not is_allowed_extension(filename):
            raise UnsupportedFileTypeError(f"File type '{ext}' is not allowed.")

        # --- Stage 1 & 2: hash + duplicate check -------------------------
        sha256 = sha256_of_file(file_obj)
        existing = Document.objects.filter(sha256_hash=sha256, is_deleted=False).first()
        if existing:
            raise DuplicateDocumentError(existing)

        # --- Stage 1: save Document record with PENDING status -----------
        file_obj.seek(0)
        file_size = self._get_file_size(file_obj)

        doc = Document(
            title=Path(filename).stem[:500],
            original_filename=safe_filename(filename),
            file_size=file_size,
            extension=ext,
            file_category=get_file_category(filename),
            sha256_hash=sha256,
            knowledge_base=knowledge_base,
            status=Document.Status.PENDING,
            created_by=uploaded_by,
            modified_by=uploaded_by,
            parent_document=parent_document,
        )
        file_obj.seek(0)
        doc.file.save(safe_filename(filename), ContentFile(file_obj.read()), save=False)
        file_obj.seek(0)
        doc.save()

        logger.info("Document #%d created: %s", doc.pk, doc.title)

        try:
            # ZIP: expand and recurse
            if ext == ".zip":
                return self._process_zip(doc, knowledge_base, uploaded_by)

            # Normal file
            return self._process_file(doc, file_obj)

        except Exception as e:
            logger.exception("Pipeline failed for document #%d", doc.pk)
            doc.status = Document.Status.FAILED
            doc.processing_error = str(e)
            doc.save(update_fields=["status", "processing_error"])
            return doc

    # ------------------------------------------------------------------
    # Internal stages
    # ------------------------------------------------------------------

    def _process_file(self, doc: Document, file_obj) -> Document:
        """Run the text-extraction + OCR + normalisation pipeline."""
        doc.status = Document.Status.PROCESSING
        doc.processing_started_at = timezone.now()
        doc.save(update_fields=["status", "processing_started_at"])

        file_obj.seek(0)
        result: ParseResult = _parser.parse(
            file_obj,
            filename=doc.original_filename,
            file_path=Path(doc.file.path) if doc.file else None,
        )

        # --- OCR stage ---------------------------------------------------
        if result.requires_ocr:
            doc.status = Document.Status.OCR_REQUIRED
            doc.requires_ocr = True
            doc.save(update_fields=["status", "requires_ocr"])
            result = self._run_ocr(doc, result)

        # --- Text extraction stage ----------------------------------------
        doc.status = Document.Status.EXTRACTING
        doc.save(update_fields=["status"])

        # Normalise and persist pages
        self._save_pages(doc, result)

        # Populate metadata from parse result
        self._apply_metadata(doc, result)

        # Save extraction state, then hand off to embedding service
        doc.status = Document.Status.CHUNKING
        doc.save()

        logger.info(
            "Document #%d extraction complete: %d pages, %d words",
            doc.pk, doc.page_count, doc.word_count,
        )

        # Phase 5: chunk → embed → index
        try:
            from core.embeddings.embedding_service import embedding_service
            summary = embedding_service.index_document(doc)
            if summary.get("error"):
                logger.warning(
                    "Embedding incomplete for doc #%d: %s",
                    doc.pk, summary["error"],
                )
        except Exception as emb_err:
            logger.error("Embedding step failed for doc #%d: %s", doc.pk, emb_err)
            # Leave status as CHUNKING so the reindex command can retry later
            doc.status = Document.Status.CHUNKING
            doc.save(update_fields=["status"])

        return doc

    def _run_ocr(self, doc: Document, prior_result: ParseResult) -> ParseResult:
        """Run Tesseract OCR and merge results back into a ParseResult."""
        from apps.document_upload.models import DocumentPage as DP

        job = OCRJob.objects.create(
            document=doc,
            status=OCRJob.Status.RUNNING,
            engine="tesseract",
            engine_version=_ocr.get_version(),
            language="eng",
            started_at=timezone.now(),
        )

        try:
            file_path = Path(doc.file.path)
            ext = doc.extension.lower()

            if ext == ".pdf":
                ocr_output = _ocr.ocr_pdf(file_path)
            elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif"):
                ocr_output = _ocr.ocr_image_file(file_path)
            else:
                # Shouldn't happen, but fail gracefully
                job.status = OCRJob.Status.FAILED
                job.error_message = f"OCR not supported for {ext}"
                job.save()
                return prior_result

            # Persist per-page results
            for page in ocr_output.pages:
                OCRPageResult.objects.create(
                    job=job,
                    page_number=page.page_number,
                    extracted_text=page.text,
                    confidence=page.confidence,
                    duration_seconds=page.duration_seconds,
                    error_message=page.error,
                )

            job.status = (
                OCRJob.Status.COMPLETED if ocr_output.failed_pages == 0
                else OCRJob.Status.FAILED
            )
            job.completed_at = timezone.now()
            job.pages_processed = len(ocr_output.pages)
            job.pages_failed = ocr_output.failed_pages
            job.average_confidence = ocr_output.average_confidence
            job.save()

            doc.ocr_completed = True
            doc.save(update_fields=["ocr_completed"])

            # Convert OCR output to ParseResult format
            from core.services.parsers import PageResult, ParseResult as PR
            pages = [
                PageResult(page_number=p.page_number, text=p.text)
                for p in ocr_output.pages
            ]
            return PR(pages=pages, requires_ocr=True)

        except Exception as e:
            logger.exception("OCR failed for document #%d", doc.pk)
            job.status = OCRJob.Status.FAILED
            job.error_message = str(e)
            job.completed_at = timezone.now()
            job.save()
            return prior_result   # return whatever text we had

    def _save_pages(self, doc: Document, result: ParseResult) -> None:
        """Persist DocumentPage rows in bulk."""
        # Delete any stale pages from a previous attempt
        doc.pages.all().delete()

        pages_to_create = []
        for page in result.pages:
            normalised = normalize_text(page.text)
            pages_to_create.append(DocumentPage(
                document=doc,
                page_number=page.page_number,
                raw_text=normalised,
                word_count=count_words(normalised),
                is_ocr=result.requires_ocr,
                created_by=doc.created_by,
                modified_by=doc.modified_by,
            ))
        DocumentPage.objects.bulk_create(pages_to_create, batch_size=100)

    def _apply_metadata(self, doc: Document, result: ParseResult) -> None:
        """Write parse-extracted metadata onto the Document."""
        meta = result.metadata
        doc.page_count = result.page_count
        doc.word_count = result.total_word_count

        if not doc.title or doc.title == Path(doc.original_filename).stem:
            doc.title = meta.get("Title", doc.title)[:500]

        author = meta.get("Author", "")
        if author:
            doc.author = author[:255]

        # Parse ISO date strings best-effort
        for field_name, meta_key in [("doc_created_at", "CreationDate"), ("doc_modified_at", "ModDate")]:
            raw = meta.get(meta_key, "")
            if raw:
                try:
                    from django.utils.dateparse import parse_datetime
                    dt = parse_datetime(raw[:19].replace("D:", "").replace("'", ":"))
                    if dt:
                        setattr(doc, field_name, dt)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # ZIP handling
    # ------------------------------------------------------------------

    def _process_zip(self, zip_doc: Document, knowledge_base, uploaded_by) -> Document:
        """
        Extract every file from the ZIP and ingest each one.
        Spec: "If ZIP is uploaded — Automatically extract / Scan every file / Index every document"
        """
        zip_doc.status = Document.Status.PROCESSING
        zip_doc.processing_started_at = timezone.now()
        zip_doc.save(update_fields=["status", "processing_started_at"])

        extracted_count = 0
        failed_count = 0
        tmpdir = tempfile.mkdtemp(prefix="kb_zip_")

        try:
            with zipfile.ZipFile(zip_doc.file.path, "r") as zf:
                # Security: skip path traversal and hidden entries
                safe_entries = [
                    entry for entry in zf.infolist()
                    if not entry.filename.startswith(("/", ".."))
                    and not os.path.basename(entry.filename).startswith(".")
                    and not entry.is_dir()
                    and is_allowed_extension(entry.filename)
                ]

                logger.info(
                    "ZIP %s: %d eligible files to extract",
                    zip_doc.original_filename, len(safe_entries),
                )

                for entry in safe_entries:
                    try:
                        data = zf.read(entry.filename)
                        child_name = safe_filename(os.path.basename(entry.filename))
                        file_obj = io.BytesIO(data)
                        file_obj.name = child_name

                        self.ingest(
                            file_obj=file_obj,
                            filename=child_name,
                            knowledge_base=knowledge_base,
                            uploaded_by=uploaded_by,
                            parent_document=zip_doc,
                        )
                        extracted_count += 1
                    except DuplicateDocumentError:
                        logger.info("ZIP child %s is a duplicate — skipping", entry.filename)
                    except UnsupportedFileTypeError:
                        logger.debug("ZIP child %s has unsupported type — skipping", entry.filename)
                    except Exception as e:
                        logger.error("Failed to ingest ZIP child %s: %s", entry.filename, e)
                        failed_count += 1

            zip_doc.status = Document.Status.INDEXED
            zip_doc.page_count = extracted_count
            zip_doc.processing_completed_at = timezone.now()
            zip_doc.processing_error = (
                f"{failed_count} files failed" if failed_count else ""
            )
            zip_doc.save()
            logger.info(
                "ZIP #%d processed: %d extracted, %d failed",
                zip_doc.pk, extracted_count, failed_count,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return zip_doc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_file_size(file_obj) -> int:
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)
        return size
