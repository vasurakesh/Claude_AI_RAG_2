"""
core/utilities/text_utils.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Text normalisation helpers.
Implements spec: Normalize Unicode / Remove unwanted spaces / Remove headers and footers.
"""

import re
import unicodedata
import logging
from collections import Counter

logger = logging.getLogger(__name__)


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = text.replace("\f", "\n")
    return text


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines)


def remove_headers_footers(text: str) -> str:
    pages = re.split(r"\n{2,}", text)
    if len(pages) < 3:
        return text
    line_counts: Counter = Counter()
    for page in pages:
        seen: set = set()
        for line in page.split("\n"):
            stripped = line.strip()
            if stripped and len(stripped) < 120 and stripped not in seen:
                line_counts[stripped] += 1
                seen.add(stripped)
    threshold = max(3, int(len(pages) * 0.25))
    boilerplate = {line for line, count in line_counts.items() if count >= threshold}
    if not boilerplate:
        return text
    cleaned = []
    for page in pages:
        lines = [l for l in page.split("\n") if l.strip() not in boilerplate]
        cleaned.append("\n".join(lines))
    return "\n\n".join(cleaned)


def normalize_text(text: str) -> str:
    """Master pipeline: unicode → headers/footers → whitespace."""
    if not text:
        return ""
    text = normalize_unicode(text)
    text = remove_headers_footers(text)
    text = normalize_whitespace(text)
    return text.strip()


# Keep clean_extracted_text as alias so any existing imports still work
clean_extracted_text = normalize_text


def count_words(text: str) -> int:
    return len(text.split()) if text else 0


def is_text_sparse(text: str, min_words_per_page: int = 20) -> bool:
    return count_words(text) < min_words_per_page
