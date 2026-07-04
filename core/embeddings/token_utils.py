"""
core/embeddings/token_utils.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Token counting that works offline on Windows.

- Tries tiktoken (cl100k_base) on first call and caches the result.
- Falls back to a character-based estimate (4 chars ≈ 1 token) if tiktoken
  BPE vocab is unavailable (sandbox / no-internet environments).
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_encoder = None          # cached tiktoken encoder
_tiktoken_failed = False # once True, never retry


def _get_encoder():
    global _encoder, _tiktoken_failed
    if _encoder is not None:
        return _encoder
    if _tiktoken_failed:
        return None
    try:
        import tiktoken
        _encoder = tiktoken.get_encoding("cl100k_base")
        return _encoder
    except Exception as e:
        logger.warning(
            "tiktoken unavailable (%s); falling back to char-based token estimate.", e
        )
        _tiktoken_failed = True
        return None


def count_tokens(text: str) -> int:
    """Return the approximate token count for text."""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Fallback: 1 token ≈ 4 characters (reasonable for English prose)
    return max(1, len(text) // 4)


def split_text_by_tokens(
    text: str,
    max_tokens: int,
    overlap_tokens: int = 0,
) -> list[str]:
    """
    Split text into token-aware chunks of at most max_tokens each,
    with overlap_tokens tokens of context carried between chunks.
    Works without tiktoken by splitting on whitespace when the encoder
    is unavailable.
    """
    if not text.strip():
        return []

    enc = _get_encoder()

    if enc is not None:
        try:
            token_ids = enc.encode(text)
            if len(token_ids) <= max_tokens:
                return [text]
            chunks = []
            start = 0
            while start < len(token_ids):
                end = min(start + max_tokens, len(token_ids))
                chunk_tokens = token_ids[start:end]
                chunks.append(enc.decode(chunk_tokens))
                if end == len(token_ids):
                    break
                start = end - overlap_tokens
            return [c for c in chunks if c.strip()]
        except Exception:
            pass

    # Fallback: word-based split (1 word ≈ 0.75 tokens)
    words = text.split()
    words_per_chunk = max(1, int(max_tokens * 0.75))
    overlap_words  = max(0, int(overlap_tokens * 0.75))
    chunks, start = [], 0
    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_words
    return [c for c in chunks if c.strip()]
