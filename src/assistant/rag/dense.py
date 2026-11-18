"""Stage 2: bi-encoder + FAISS HNSW (design.md Gate 3). Cosine via normalized inner product.

Model default is bge-large-en-v1.5 (design). BGE query instruction is applied to queries only.
"""
from __future__ import annotations

import numpy as np

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class DenseIndex:
    def __init__(self, texts: list[str], chunk_ids: list[str], model_name: str = "BAAI/bge-large-en-v1.5",
                 ef_search: int = 64, m: int = 32, encoder=None) -> None:
        import faiss  # imported lazily so lexical-only installs still work

        if len(texts) != len(chunk_ids):
            raise ValueError("texts and chunk_ids must align")
        if encoder is None:
            from sentence_transformers import SentenceTransformer
            encoder = SentenceTransformer(model_name)
        self.encoder = encoder
        self.chunk_ids = chunk_ids
        vectors = self._encode(texts, prefix="")
        self.dim = vectors.shape[1]
        self.index = faiss.IndexHNSWFlat(self.dim, m, faiss.METRIC_INNER_PRODUCT)
        self.index.hnsw.efConstruction = 200
        self.index.add(vectors)
        self.index.hnsw.efSearch = ef_search

    def _encode(self, texts: list[str], prefix: str) -> np.ndarray:
        vecs = self.encoder.encode([prefix + t for t in texts], normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")

    def search(self, query: str, top_k: int = 50) -> list[tuple[str, float]]:
        """Returns [(chunk_id, cosine)] sorted by cosine, best first."""
        if not self.chunk_ids:
            return []
        q = self._encode([query], prefix=BGE_QUERY_PREFIX)
        k = min(top_k, len(self.chunk_ids))
        scores, idx = self.index.search(q, k)
        return [(self.chunk_ids[i], float(s)) for s, i in zip(scores[0], idx[0]) if i >= 0]
