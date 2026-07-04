"""
core/embeddings/vector_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vector database abstraction layer (spec: "abstract the vector database
behind a service so another backend can be swapped later").

Public API (VectorStoreBase):
  add(chunk_id, vector, metadata)   — upsert one embedding
  add_batch(items)                  — upsert many
  search(query_vector, top_k, ...)  — ANN search
  delete(chunk_id)                  — remove one
  delete_by_document(document_id)   — remove all chunks for a document
  count()                           — total vectors stored
  health_check()                    — returns bool

Two concrete backends:
  ChromaDBStore  — persistent ChromaDB collection (recommended default)
  FAISSStore     — in-process FAISS flat-IP index with JSON metadata sidecar

VectorStoreFactory.get()  — reads VECTOR_DB_BACKEND from settings and
                             returns the correct singleton.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SearchHit:
    chunk_id: str
    score: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class VectorStoreBase(ABC):

    @abstractmethod
    def add(self, chunk_id: str, vector: list[float], metadata: dict) -> None:
        ...

    @abstractmethod
    def add_batch(
        self, items: list[tuple[str, list[float], dict]]
    ) -> None:
        ...

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        where: Optional[dict] = None,
    ) -> list[SearchHit]:
        ...

    @abstractmethod
    def delete(self, chunk_id: str) -> None:
        ...

    @abstractmethod
    def delete_by_document(self, document_id: int) -> None:
        ...

    @abstractmethod
    def count(self) -> int:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...


# ---------------------------------------------------------------------------
# Backend 1 — ChromaDB
# ---------------------------------------------------------------------------

CHROMA_COLLECTION_NAME = "kb_platform_chunks"


class ChromaDBStore(VectorStoreBase):
    """
    Persistent ChromaDB backend.
    Data is stored in VECTOR_DB_PERSIST_DIR/chroma/.
    ChromaDB uses cosine distance by default (configured at collection creation).
    """

    def __init__(self, persist_dir: str):
        self.persist_dir = os.path.join(persist_dir, "chroma")
        os.makedirs(self.persist_dir, exist_ok=True)
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            self._client = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB collection '%s' ready at %s",
                CHROMA_COLLECTION_NAME, self.persist_dir,
            )
            return self._collection
        except ImportError:
            raise RuntimeError(
                "chromadb not installed. Run: pip install chromadb"
            )
        except Exception as e:
            raise RuntimeError(f"ChromaDB init failed: {e}") from e

    def add(self, chunk_id: str, vector: list[float], metadata: dict) -> None:
        col = self._get_collection()
        # Sanitise metadata: ChromaDB only accepts str/int/float/bool
        clean_meta = {
            k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
            for k, v in metadata.items()
            if v is not None
        }
        col.upsert(
            ids=[chunk_id],
            embeddings=[vector],
            metadatas=[clean_meta],
        )

    def add_batch(self, items: list[tuple[str, list[float], dict]]) -> None:
        if not items:
            return
        col = self._get_collection()
        ids, embeddings, metadatas = [], [], []
        for chunk_id, vector, metadata in items:
            clean_meta = {
                k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
                for k, v in metadata.items()
                if v is not None
            }
            ids.append(chunk_id)
            embeddings.append(vector)
            metadatas.append(clean_meta)
        col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)
        logger.debug("ChromaDB: upserted %d vectors", len(ids))

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        where: Optional[dict] = None,
    ) -> list[SearchHit]:
        col = self._get_collection()
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": min(top_k, max(1, self.count())),
            "include": ["metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        try:
            results = col.query(**kwargs)
        except Exception as e:
            logger.error("ChromaDB search error: %s", e)
            return []

        hits = []
        ids       = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        for chunk_id, dist, meta in zip(ids, distances, metas):
            # ChromaDB cosine distance: score = 1 - distance
            hits.append(SearchHit(
                chunk_id=chunk_id,
                score=round(1.0 - float(dist), 6),
                metadata=meta or {},
            ))
        return hits

    def delete(self, chunk_id: str) -> None:
        try:
            self._get_collection().delete(ids=[chunk_id])
        except Exception as e:
            logger.warning("ChromaDB delete failed for %s: %s", chunk_id, e)

    def delete_by_document(self, document_id: int) -> None:
        try:
            col = self._get_collection()
            col.delete(where={"document_id": str(document_id)})
        except Exception as e:
            logger.warning(
                "ChromaDB delete_by_document failed for doc %d: %s", document_id, e
            )

    def count(self) -> int:
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    def health_check(self) -> bool:
        try:
            self._get_collection()
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Backend 2 — FAISS
# ---------------------------------------------------------------------------

FAISS_INDEX_FILE  = "faiss_index.bin"
FAISS_META_FILE   = "faiss_meta.json"


class FAISSStore(VectorStoreBase):
    """
    In-process FAISS flat index (IndexFlatIP = inner product on L2-normalised
    vectors ≡ cosine similarity).

    Metadata is stored in a JSON sidecar file alongside the binary index.
    The index is loaded once at startup and persisted after every batch write.
    """

    def __init__(self, persist_dir: str):
        self.persist_dir = os.path.join(persist_dir, "faiss")
        os.makedirs(self.persist_dir, exist_ok=True)
        self.index_path = os.path.join(self.persist_dir, FAISS_INDEX_FILE)
        self.meta_path  = os.path.join(self.persist_dir, FAISS_META_FILE)
        self._index = None
        self._meta: dict[str, dict] = {}   # chunk_id → {"faiss_pos": int, **metadata}
        self._id_to_pos: dict[str, int] = {}
        self._pos_to_id: dict[int, str] = {}
        self._dims: Optional[int] = None
        self._dirty = False
        self._load()

    def _load(self):
        """Load index and metadata from disk if they exist."""
        try:
            import faiss
            if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
                self._index = faiss.read_index(self.index_path)
                with open(self.meta_path) as f:
                    raw = json.load(f)
                self._meta      = raw.get("meta", {})
                self._id_to_pos = {k: v["faiss_pos"] for k, v in self._meta.items()}
                self._pos_to_id = {v: k for k, v in self._id_to_pos.items()}
                self._dims      = raw.get("dims")
                logger.info(
                    "FAISS index loaded: %d vectors, dims=%d",
                    self._index.ntotal, self._dims or 0,
                )
        except Exception as e:
            logger.warning("FAISS load failed (starting fresh): %s", e)
            self._index = None

    def _save(self):
        try:
            import faiss
            faiss.write_index(self._index, self.index_path)
            with open(self.meta_path, "w") as f:
                json.dump({"meta": self._meta, "dims": self._dims}, f)
            self._dirty = False
        except Exception as e:
            logger.error("FAISS save failed: %s", e)

    def _ensure_index(self, dims: int):
        if self._index is None:
            import faiss
            self._index = faiss.IndexFlatIP(dims)
            self._dims = dims

    @staticmethod
    def _normalise(vector: list[float]) -> list[float]:
        """L2-normalise so inner product == cosine similarity."""
        import math
        mag = math.sqrt(sum(x * x for x in vector))
        if mag == 0:
            return vector
        return [x / mag for x in vector]

    def add(self, chunk_id: str, vector: list[float], metadata: dict) -> None:
        self.add_batch([(chunk_id, vector, metadata)])

    def add_batch(self, items: list[tuple[str, list[float], dict]]) -> None:
        if not items:
            return
        import numpy as np
        dims = len(items[0][1])
        self._ensure_index(dims)

        vectors, new_ids = [], []
        for chunk_id, vector, metadata in items:
            norm_vec = self._normalise(vector)
            if chunk_id in self._id_to_pos:
                # FAISS flat index has no update — we skip (re-index removes stale)
                continue
            pos = self._index.ntotal + len(vectors)
            self._id_to_pos[chunk_id] = pos
            self._pos_to_id[pos] = chunk_id
            self._meta[chunk_id] = {"faiss_pos": pos, **metadata}
            vectors.append(norm_vec)
            new_ids.append(chunk_id)

        if vectors:
            mat = np.array(vectors, dtype="float32")
            self._index.add(mat)
            self._dirty = True

        self._save()
        logger.debug("FAISS: added %d vectors (total=%d)", len(vectors), self._index.ntotal)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        where: Optional[dict] = None,
    ) -> list[SearchHit]:
        if self._index is None or self._index.ntotal == 0:
            return []
        import numpy as np
        norm_q = self._normalise(query_vector)
        mat = np.array([norm_q], dtype="float32")
        k = min(top_k * 3, self._index.ntotal)   # oversample for post-filter
        scores, indices = self._index.search(mat, k)

        hits = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk_id = self._pos_to_id.get(int(idx))
            if not chunk_id:
                continue
            meta = dict(self._meta.get(chunk_id, {}))
            meta.pop("faiss_pos", None)

            # Post-filter by metadata (where clause)
            if where:
                if not all(str(meta.get(k)) == str(v) for k, v in where.items()):
                    continue

            hits.append(SearchHit(
                chunk_id=chunk_id,
                score=round(float(score), 6),
                metadata=meta,
            ))
            if len(hits) >= top_k:
                break
        return hits

    def delete(self, chunk_id: str) -> None:
        # FAISS flat index doesn't support individual deletion.
        # Mark as deleted in metadata; rebuild periodically (Phase 8).
        if chunk_id in self._meta:
            del self._meta[chunk_id]
            pos = self._id_to_pos.pop(chunk_id, None)
            if pos is not None:
                del self._pos_to_id[pos]
            self._save()

    def delete_by_document(self, document_id: int) -> None:
        to_delete = [
            cid for cid, meta in self._meta.items()
            if str(meta.get("document_id")) == str(document_id)
        ]
        for cid in to_delete:
            self.delete(cid)

    def count(self) -> int:
        return len(self._meta)   # excludes soft-deleted entries

    def health_check(self) -> bool:
        try:
            import faiss  # noqa: F401
            return True
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_store_instance: Optional[VectorStoreBase] = None


class VectorStoreFactory:

    @classmethod
    def get(cls) -> VectorStoreBase:
        """Return the configured vector store singleton."""
        global _store_instance
        if _store_instance is not None:
            return _store_instance

        backend    = getattr(settings, "VECTOR_DB_BACKEND", "chromadb")
        persist_dir = getattr(settings, "VECTOR_DB_PERSIST_DIR", "vector_store")

        logger.info("Initialising vector store backend: %s", backend)
        if backend == "faiss":
            _store_instance = FAISSStore(persist_dir)
        else:
            _store_instance = ChromaDBStore(persist_dir)

        return _store_instance

    @classmethod
    def reset(cls):
        """Force re-initialisation (useful in tests)."""
        global _store_instance
        _store_instance = None
