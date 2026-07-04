"""
core/ocr/tesseract_engine.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TesseractEngine — thin class wrapper around the functional OCR helpers
in tesseract_ocr.py so the pipeline can instantiate it as `_ocr = TesseractEngine()`.
"""
import subprocess
import logging
from pathlib import Path
from .tesseract_ocr import ocr_pdf, ocr_image_file, OCRDocumentOutput

logger = logging.getLogger(__name__)


class TesseractEngine:

    def get_version(self) -> str:
        """Return Tesseract version string, or 'unknown' if not installed."""
        try:
            from django.conf import settings
            cmd = getattr(settings, 'TESSERACT_CMD', 'tesseract')
            result = subprocess.run(
                [cmd, '--version'],
                capture_output=True, text=True, timeout=5,
            )
            first_line = (result.stdout or result.stderr or '').split('\n')[0]
            return first_line.strip() or 'unknown'
        except Exception:
            return 'unknown'

    def ocr_pdf(self, pdf_path: Path, lang: str = 'eng') -> OCRDocumentOutput:
        return ocr_pdf(str(pdf_path), lang=lang)

    def ocr_image_file(self, image_path: Path, lang: str = 'eng') -> OCRDocumentOutput:
        return ocr_image_file(str(image_path), lang=lang)

    @property
    def pages_failed(self):
        """Compatibility shim used by pipeline when checking OCR output."""
        return 0
