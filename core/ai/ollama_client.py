"""
core/ai/ollama_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Thin wrapper around the official ollama Python SDK.

Design decisions:
- OllamaClient is a singleton per process (instantiated once at module level).
- All public methods raise OllamaError on failure so callers can handle
  connectivity problems gracefully without importing ollama directly.
- embed() and embed_batch() are the primary Phase 5 entry points.
- generate() / chat() are wired in Phase 6 (RAG pipeline).
- is_online() is used by the dashboard health check.
"""

import logging
import time
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when the Ollama API is unreachable or returns an error."""


class OllamaClient:

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or getattr(
            settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        )
        self._client = None

    def _get_client(self):
        """Lazy-init the ollama SDK client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self.base_url)
            except ImportError:
                raise OllamaError(
                    "ollama package not installed. Run: pip install ollama"
                )
        return self._client

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """Return True if Ollama server is reachable."""
        try:
            client = self._get_client()
            client.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[dict]:
        """Return list of locally available Ollama models."""
        try:
            client = self._get_client()
            resp = client.list()
            return resp.get("models", [])
        except Exception as e:
            raise OllamaError(f"Failed to list models: {e}") from e

    # ------------------------------------------------------------------
    # Embeddings (Phase 5)
    # ------------------------------------------------------------------

    def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        """
        Generate an embedding vector for a single text string.
        Returns a list of floats.
        """
        model = model or getattr(settings, "DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")
        if not text or not text.strip():
            raise OllamaError("Cannot embed empty text.")
        try:
            client = self._get_client()
            resp = client.embeddings(model=model, prompt=text)
            vector = resp.get("embedding") or resp.get("embeddings", [[]])[0]
            if not vector:
                raise OllamaError(f"Ollama returned empty embedding for model '{model}'")
            return vector
        except OllamaError:
            raise
        except Exception as e:
            raise OllamaError(f"Embedding generation failed: {e}") from e

    def embed_batch(
        self,
        texts: list[str],
        model: Optional[str] = None,
        batch_size: int = 32,
    ) -> list[list[float]]:
        """
        Generate embeddings for a list of texts.
        Processes in batches of batch_size to avoid overwhelming Ollama.
        Returns list of float vectors in the same order as input texts.
        """
        model = model or getattr(settings, "DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")
        results: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]
            logger.debug(
                "Embedding batch %d-%d of %d texts (model=%s)",
                i + 1, min(i + batch_size, total), total, model,
            )
            for text in batch:
                vector = self.embed(text, model=model)
                results.append(vector)

        return results

    # ------------------------------------------------------------------
    # Generation (Phase 6 — included here so the client is complete)
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: str = "",
        temperature: float = 0.1,
        top_p: float = 0.9,
        top_k: int = 40,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> dict:
        """
        Non-streaming text generation.
        Returns dict with keys: response, model, done, total_duration,
        prompt_eval_count, eval_count.
        """
        model = model or getattr(settings, "DEFAULT_LLM_MODEL", "qwen3:14b-instruct")
        try:
            client = self._get_client()
            kwargs = dict(
                model=model,
                prompt=prompt,
                options={
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "num_predict": max_tokens,
                },
                stream=False,
            )
            if system:
                kwargs["system"] = system
            resp = client.generate(**kwargs)
            return dict(resp)
        except Exception as e:
            raise OllamaError(f"Generation failed: {e}") from e

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.1,
        top_p: float = 0.9,
        top_k: int = 40,
        max_tokens: int = 1024,
    ) -> dict:
        """
        Multi-turn chat endpoint.
        messages: list of {"role": "user"|"assistant"|"system", "content": str}
        Returns dict with keys: message (dict with role/content), model, done.
        """
        model = model or getattr(settings, "DEFAULT_LLM_MODEL", "qwen3:14b-instruct")
        try:
            client = self._get_client()
            resp = client.chat(
                model=model,
                messages=messages,
                options={
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "num_predict": max_tokens,
                },
                stream=False,
            )
            return dict(resp)
        except Exception as e:
            raise OllamaError(f"Chat failed: {e}") from e


# Module-level singleton — import this everywhere
ollama_client = OllamaClient()
