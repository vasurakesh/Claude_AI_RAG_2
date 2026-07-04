"""
core/ocr/tesseract_ocr.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Tesseract OCR wrapper for scanned PDFs and images.

Design decisions:
- pytesseract.image_to_data() is used instead of image_to_string() so we
  get per-word confidence scores to compute average page confidence.
- pdf2image converts each PDF page to a PIL Image at 300 DPI (optimal for
  Tesseract accuracy vs speed trade-off on A4/letter documents).
- TESSERACT_CMD and POPPLER_PATH are read from Django settings so Windows
  install paths are configured via .env without code changes.
- Every public method returns a typed dataclass so callers don't parse dicts.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class OCRPageOutput:
    page_number: int
    text: str
    confidence: Optional[float]
    duration_seconds: float
    error: str = ""


@dataclass
class OCRDocumentOutput:
    pages: list[OCRPageOutput] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    average_confidence: Optional[float] = None
    error: str = ""

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def failed_pages(self) -> int:
        return sum(1 for p in self.pages if p.error)


def _configure_tesseract():
    """Point pytesseract at the Windows Tesseract binary if configured."""
    try:
        import pytesseract
        cmd = getattr(settings, "TESSERACT_CMD", None)
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        return pytesseract
    except ImportError:
        raise RuntimeError(
            "pytesseract is not installed. Run: pip install pytesseract"
        )


def ocr_image(image, lang: str = "eng") -> OCRPageOutput:
    """
    Run Tesseract on a single PIL Image.
    Returns OCRPageOutput with text and mean confidence.
    """
    import pytesseract
    _configure_tesseract()
    start = time.perf_counter()
    try:
        # Get data with confidence scores
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            output_type=pytesseract.Output.DICT,
        )
        words = [
            (data["text"][i], int(data["conf"][i]))
            for i in range(len(data["text"]))
            if data["text"][i].strip() and int(data["conf"][i]) > 0
        ]
        text = " ".join(w for w, _ in words)
        confidence = (
            sum(c for _, c in words) / len(words) if words else None
        )
        return OCRPageOutput(
            page_number=0,
            text=text,
            confidence=confidence,
            duration_seconds=time.perf_counter() - start,
        )
    except Exception as exc:
        logger.error("Tesseract OCR failed: %s", exc)
        return OCRPageOutput(
            page_number=0,
            text="",
            confidence=None,
            duration_seconds=time.perf_counter() - start,
            error=str(exc),
        )


def ocr_pdf(pdf_path: str, lang: str = "eng", dpi: int = 300) -> OCRDocumentOutput:
    """
    Convert a PDF to images (via pdf2image/Poppler) then OCR each page.
    """
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError

    poppler_path = getattr(settings, "POPPLER_PATH", None)
    start_total = time.perf_counter()
    result = OCRDocumentOutput()

    try:
        kwargs = {"dpi": dpi}
        if poppler_path:
            kwargs["poppler_path"] = poppler_path
        images = convert_from_path(pdf_path, **kwargs)
    except PDFInfoNotInstalledError:
        msg = (
            "Poppler is not installed or POPPLER_PATH is incorrect. "
            "Download from https://github.com/oschwartz10612/poppler-windows/releases "
            "and set POPPLER_PATH in your .env file."
        )
        logger.error(msg)
        result.error = msg
        return result
    except Exception as exc:
        logger.error("pdf2image conversion failed for %s: %s", pdf_path, exc)
        result.error = str(exc)
        return result

    for i, image in enumerate(images, start=1):
        page_result = ocr_image(image, lang=lang)
        page_result.page_number = i
        result.pages.append(page_result)
        logger.debug(
            "OCR page %d/%d — confidence=%.1f%% time=%.2fs",
            i, len(images),
            page_result.confidence or 0,
            page_result.duration_seconds,
        )

    result.total_duration_seconds = time.perf_counter() - start_total
    confident_pages = [p for p in result.pages if p.confidence is not None]
    if confident_pages:
        result.average_confidence = sum(
            p.confidence for p in confident_pages
        ) / len(confident_pages)

    logger.info(
        "OCR complete: %d pages, avg confidence=%.1f%%, total=%.2fs",
        len(result.pages),
        result.average_confidence or 0,
        result.total_duration_seconds,
    )
    return result


def ocr_image_file(image_path: str, lang: str = "eng") -> OCRDocumentOutput:
    """OCR a standalone image file (PNG, JPG, TIFF)."""
    from PIL import Image
    start = time.perf_counter()
    result = OCRDocumentOutput()
    try:
        image = Image.open(image_path)
        page_result = ocr_image(image, lang=lang)
        page_result.page_number = 1
        result.pages.append(page_result)
        result.total_duration_seconds = time.perf_counter() - start
        if page_result.confidence is not None:
            result.average_confidence = page_result.confidence
    except Exception as exc:
        logger.error("Image OCR failed for %s: %s", image_path, exc)
        result.error = str(exc)
    return result
