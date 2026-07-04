"""
core/utilities/file_utils.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
File validation, hashing, type detection and sanitisation utilities.
Used by the upload view before a file ever touches the pipeline.
"""

import hashlib
import mimetypes
import os
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

EXTENSION_CATEGORY_MAP: dict[str, str] = {
    ".pdf":  "pdf",
    ".docx": "word",  ".doc": "word",
    ".xlsx": "excel", ".xls": "excel",
    ".csv":  "csv",
    ".txt":  "text",
    ".html": "html",  ".htm": "html",
    ".rtf":  "rtf",
    ".pptx": "pptx",
    ".zip":  "archive",
    ".png":  "image", ".jpg": "image",
    ".jpeg": "image", ".tiff": "image", ".tif": "image",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif"}


def sha256_of_file(file_obj) -> str:
    """Return hex SHA-256 of a file-like object. Rewinds after reading."""
    h = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(65536), b""):
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    """Return hex SHA-256 of a bytes object."""
    return hashlib.sha256(data).hexdigest()


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def get_file_category(filename: str) -> str:
    return EXTENSION_CATEGORY_MAP.get(get_extension(filename), "unknown")


def is_allowed_extension(filename: str) -> bool:
    ext = get_extension(filename)
    allowed = [e.lower() for e in settings.ALLOWED_UPLOAD_EXTENSIONS]
    return ext in allowed


def requires_ocr_by_extension(extension: str) -> bool:
    return extension in IMAGE_EXTENSIONS


def validate_upload(file_obj, filename: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not is_allowed_extension(filename):
        ext = get_extension(filename)
        return False, f"File type '{ext}' is not allowed."
    max_bytes = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > max_bytes:
        mb = max_bytes // (1024 * 1024)
        return False, f"File too large (max {mb} MB)."
    return True, ""


def safe_filename(original: str) -> str:
    name = os.path.basename(original)
    name = name.replace("\x00", "")
    return name or "upload"
