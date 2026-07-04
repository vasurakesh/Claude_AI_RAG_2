"""
core/embeddings/chunkers.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Four chunking strategies (spec: Paragraph / Sentence / Recursive / Semantic).

Design decisions:
- Each strategy is a class with a `chunk(text, page_number) -> list[ChunkResult]` method.
- ChunkResult carries the text plus positional metadata (page, paragraph index,
  start/end char) so the embedding service can populate DocumentChunk exactly.
- ChunkerFactory.get(strategy) returns the right instance; strategy name is
  read from PlatformSetting at runtime so the admin can switch without a deploy.
- Semantic chunking uses cosine-similarity between consecutive sentence
  embeddings to find topic boundaries, requiring Ollama to be running.
  It gracefully degrades to recursive chunking if Ollama is offline.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings
from .token_utils import count_tokens, split_text_by_tokens

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    text: str
    chunk_index: int          # sequential within the document
    page_number: Optional[int] = None
    paragraph_number: Optional[int] = None
    start_char: int = 0
    end_char: int = 0
    token_count: int = 0

    def __post_init__(self):
        if not self.token_count:
            self.token_count = count_tokens(self.text)


# ---------------------------------------------------------------------------
# Strategy 1 — Paragraph
# ---------------------------------------------------------------------------

class ParagraphChunker:
    """
    Splits on double-newlines (paragraph boundaries).
    Merges short paragraphs into a single chunk until max_tokens is reached.
    """

    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 150):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(
        self, text: str, page_number: Optional[int] = None, start_index: int = 0
    ) -> list[ChunkResult]:
        paragraphs = re.split(r"\n{2,}", text.strip())
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        results: list[ChunkResult] = []
        current_parts: list[str] = []
        current_tokens = 0
        para_idx = 0
        chunk_idx = start_index

        def flush():
            nonlocal chunk_idx, para_idx, current_tokens
            if not current_parts:
                return
            chunk_text = "\n\n".join(current_parts)
            results.append(ChunkResult(
                text=chunk_text,
                chunk_index=chunk_idx,
                page_number=page_number,
                paragraph_number=para_idx,
                token_count=count_tokens(chunk_text),
            ))
            chunk_idx += 1
            current_parts.clear()
            current_tokens = 0

        for para in paragraphs:
            para_tokens = count_tokens(para)
            if para_tokens > self.max_tokens:
                flush()
                # Split the oversized paragraph recursively
                sub_chunks = split_text_by_tokens(
                    para, self.max_tokens, self.overlap_tokens
                )
                for sub in sub_chunks:
                    results.append(ChunkResult(
                        text=sub,
                        chunk_index=chunk_idx,
                        page_number=page_number,
                        paragraph_number=para_idx,
                        token_count=count_tokens(sub),
                    ))
                    chunk_idx += 1
            elif current_tokens + para_tokens > self.max_tokens:
                flush()
                current_parts.append(para)
                current_tokens = para_tokens
            else:
                current_parts.append(para)
                current_tokens += para_tokens
            para_idx += 1

        flush()
        return results


# ---------------------------------------------------------------------------
# Strategy 2 — Sentence
# ---------------------------------------------------------------------------

class SentenceChunker:
    """
    Splits into sentences using NLTK, then groups sentences into token-bounded
    chunks with overlap.
    """

    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 150):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self._nltk_ready = False

    def _ensure_nltk(self):
        if self._nltk_ready:
            return True
        try:
            import nltk
            try:
                nltk.data.find("tokenizers/punkt_tab")
            except LookupError:
                nltk.download("punkt_tab", quiet=True)
            self._nltk_ready = True
            return True
        except Exception as e:
            logger.warning("NLTK sentence tokenizer unavailable: %s", e)
            return False

    def _split_sentences(self, text: str) -> list[str]:
        if self._ensure_nltk():
            try:
                from nltk.tokenize import sent_tokenize
                return sent_tokenize(text)
            except Exception:
                pass
        # Fallback: split on '. ', '! ', '? '
        return re.split(r"(?<=[.!?])\s+", text)

    def chunk(
        self, text: str, page_number: Optional[int] = None, start_index: int = 0
    ) -> list[ChunkResult]:
        sentences = self._split_sentences(text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        results: list[ChunkResult] = []
        current_sents: list[str] = []
        current_tokens = 0
        chunk_idx = start_index

        # Estimate overlap in sentences
        overlap_sent_count = max(1, self.overlap_tokens // 20)

        def flush():
            nonlocal chunk_idx, current_tokens
            if not current_sents:
                return
            chunk_text = " ".join(current_sents)
            results.append(ChunkResult(
                text=chunk_text,
                chunk_index=chunk_idx,
                page_number=page_number,
                token_count=count_tokens(chunk_text),
            ))
            chunk_idx += 1

        for sent in sentences:
            sent_tokens = count_tokens(sent)
            if current_tokens + sent_tokens > self.max_tokens and current_sents:
                flush()
                # Keep last N sentences as overlap
                overlap_sents = current_sents[-overlap_sent_count:]
                current_sents = overlap_sents + [sent]
                current_tokens = sum(count_tokens(s) for s in current_sents)
            else:
                current_sents.append(sent)
                current_tokens += sent_tokens

        flush()
        return results


# ---------------------------------------------------------------------------
# Strategy 3 — Recursive (default, spec default)
# ---------------------------------------------------------------------------

class RecursiveChunker:
    """
    Attempts to split on paragraph breaks, then sentence breaks, then
    whitespace — trying each separator in order until chunks are small enough.
    This is the most robust strategy for mixed-content documents.
    """

    SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]

    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 150):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def _split(self, text: str, separators: list[str]) -> list[str]:
        if not separators:
            return [text]
        sep = separators[0]
        if sep == "":
            # Last resort: hard split by token count
            return split_text_by_tokens(text, self.max_tokens, self.overlap_tokens)

        parts = text.split(sep) if sep else [text]
        parts = [p for p in parts if p.strip()]

        results, current, current_tokens = [], [], 0

        for part in parts:
            part_tokens = count_tokens(part)
            if part_tokens > self.max_tokens:
                # Recursively split this oversized piece
                if current:
                    results.append(sep.join(current))
                    current, current_tokens = [], 0
                sub = self._split(part, separators[1:])
                results.extend(sub)
            elif current_tokens + part_tokens > self.max_tokens:
                results.append(sep.join(current))
                # Overlap: carry last portion
                if current:
                    overlap_text = sep.join(current[-1:])
                    current = [overlap_text, part]
                    current_tokens = count_tokens(overlap_text) + part_tokens
                else:
                    current = [part]
                    current_tokens = part_tokens
            else:
                current.append(part)
                current_tokens += part_tokens

        if current:
            results.append(sep.join(current))

        return [r for r in results if r.strip()]

    def chunk(
        self, text: str, page_number: Optional[int] = None, start_index: int = 0
    ) -> list[ChunkResult]:
        raw_chunks = self._split(text.strip(), self.SEPARATORS)
        results = []
        for i, chunk_text in enumerate(raw_chunks):
            results.append(ChunkResult(
                text=chunk_text,
                chunk_index=start_index + i,
                page_number=page_number,
                token_count=count_tokens(chunk_text),
            ))
        return results


# ---------------------------------------------------------------------------
# Strategy 4 — Semantic
# ---------------------------------------------------------------------------

class SemanticChunker:
    """
    Groups consecutive sentences into chunks by detecting topic shifts
    using cosine similarity between adjacent sentence embeddings.

    Requires Ollama to be running. Falls back to RecursiveChunker if
    the embedding call fails.
    """

    SIMILARITY_THRESHOLD = 0.75   # below this → start a new chunk

    def __init__(
        self,
        max_tokens: int = 1024,
        overlap_tokens: int = 150,
        embedding_model: Optional[str] = None,
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.embedding_model = embedding_model or getattr(
            settings, "DEFAULT_EMBEDDING_MODEL", "nomic-embed-text"
        )
        self._fallback = RecursiveChunker(max_tokens, overlap_tokens)

    def _cosine(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(x * x for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        import ollama as ollama_client
        results = []
        base_url = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        client = ollama_client.Client(host=base_url)
        for text in texts:
            resp = client.embeddings(model=self.embedding_model, prompt=text)
            results.append(resp["embedding"])
        return results

    def chunk(
        self, text: str, page_number: Optional[int] = None, start_index: int = 0
    ) -> list[ChunkResult]:
        # Split into sentences first
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        if len(sentences) < 3:
            return self._fallback.chunk(text, page_number, start_index)

        # Get embeddings for each sentence
        try:
            embeddings = self._embed_batch(sentences)
        except Exception as e:
            logger.warning(
                "Semantic chunking: embedding call failed (%s). Falling back to recursive.", e
            )
            return self._fallback.chunk(text, page_number, start_index)

        # Find breakpoints where cosine similarity drops below threshold
        breakpoints = []
        for i in range(1, len(sentences)):
            sim = self._cosine(embeddings[i - 1], embeddings[i])
            if sim < self.SIMILARITY_THRESHOLD:
                breakpoints.append(i)

        # Build groups from breakpoints
        groups: list[list[str]] = []
        prev = 0
        for bp in breakpoints:
            groups.append(sentences[prev:bp])
            prev = bp
        groups.append(sentences[prev:])

        # Merge groups into token-bounded chunks
        results, current_sents, current_tokens = [], [], 0
        chunk_idx = start_index

        for group in groups:
            group_text = " ".join(group)
            group_tokens = count_tokens(group_text)

            if current_tokens + group_tokens > self.max_tokens and current_sents:
                chunk_text = " ".join(current_sents)
                results.append(ChunkResult(
                    text=chunk_text,
                    chunk_index=chunk_idx,
                    page_number=page_number,
                    token_count=count_tokens(chunk_text),
                ))
                chunk_idx += 1
                current_sents = group
                current_tokens = group_tokens
            else:
                current_sents.extend(group)
                current_tokens += group_tokens

        if current_sents:
            chunk_text = " ".join(current_sents)
            results.append(ChunkResult(
                text=chunk_text,
                chunk_index=chunk_idx,
                page_number=page_number,
                token_count=count_tokens(chunk_text),
            ))

        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class ChunkerFactory:
    """
    Returns the appropriate chunker instance for a given strategy name.
    Strategy name comes from PlatformSetting 'chunking.strategy' at runtime.
    """

    _REGISTRY = {
        "paragraph": ParagraphChunker,
        "sentence":  SentenceChunker,
        "recursive": RecursiveChunker,
        "semantic":  SemanticChunker,
    }

    @classmethod
    def get(
        cls,
        strategy: str,
        max_tokens: int,
        overlap_tokens: int,
        **kwargs,
    ):
        klass = cls._REGISTRY.get(strategy, RecursiveChunker)
        return klass(max_tokens=max_tokens, overlap_tokens=overlap_tokens, **kwargs)

    @classmethod
    def strategies(cls) -> list[str]:
        return list(cls._REGISTRY.keys())
