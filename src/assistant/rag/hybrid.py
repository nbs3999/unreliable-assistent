"""Hybrid retrieval: BM25 + dense -> RRF (k=60, pool 40) -> cross-encoder -> threshold (0.42).

Any stage can be missing; the result lists it in `degraded` instead of failing silently.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from assistant.rag.bm25 import BM25, tokenize
from assistant.rag.dense import DenseIndex
from assistant.rag.knowledge import Chunk, KnowledgeBase
from assistant.rag.reranker import LexicalReranker, Reranker
from assistant.rag.rrf import reciprocal_rank_fusion


@dataclass
class RetrievalResult:
    abstain: bool
    chunks: list[dict] = field(default_factory=list)
    stage_ms: dict[str, float] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # fused pool, chunk ids, for evaluation


def retrieve(kb: KnowledgeBase, query: str, *, dense: DenseIndex | None = None,
             reranker: Reranker | None = None, top_k: int = 50, pool: int = 40,
             rerank_k: int = 4, threshold: float = 0.42) -> RetrievalResult:
    stage: dict[str, float] = {}
    degraded: list[str] = []
    by_id: dict[str, Chunk] = {c.chunk_id: c for c in kb.chunks}

    t = time.perf_counter()
    bm = BM25([tokenize(c.search_text) for c in kb.chunks])
    bm_scores = bm.scores(tokenize(query))
    bm_order = sorted((i for i, s in enumerate(bm_scores) if s > 0), key=lambda i: -bm_scores[i])[:top_k]
    lexical_ids = [kb.chunks[i].chunk_id for i in bm_order]
    stage["bm25"] = (time.perf_counter() - t) * 1000

    cosine: dict[str, float] = {}
    dense_ids: list[str] = []
    if dense is None:
        degraded.append("dense_unavailable")
    else:
        t = time.perf_counter()
        hits = dense.search(query, top_k=top_k)
        dense_ids = [cid for cid, _ in hits]
        cosine = dict(hits)
        stage["dense"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    rankings = [r for r in (lexical_ids, dense_ids) if r]
    fused = reciprocal_rank_fusion(rankings, k=60, pool=pool)
    stage["rrf"] = (time.perf_counter() - t) * 1000
    candidates = [cid for cid, _ in fused]

    t = time.perf_counter()
    rr = reranker
    if rr is None:
        rr = LexicalReranker()
        degraded.append("reranker_fallback_lexical")
    scores = rr.score(query, [by_id[cid].text for cid in candidates]) if candidates else []
    rescored = sorted(zip(scores, candidates), key=lambda x: (-x[0], candidates.index(x[1])))
    stage["rerank"] = (time.perf_counter() - t) * 1000

    passing = [(s, cid) for s, cid in rescored[:rerank_k] if s >= threshold]
    chunks = []
    for s, cid in passing:
        c = by_id[cid]
        bm_idx = next((i for i in bm_order if kb.chunks[i].chunk_id == cid), None)
        chunks.append({
            "chunk_id": c.chunk_id, "chunk_hash": c.chunk_hash, "text": c.text[:4096],
            "bm25": round(float(bm_scores[bm_idx]) if bm_idx is not None else 0.0, 6),
            "cosine": round(float(cosine.get(cid, 0.0)), 6),
            "rrf_rank": min(candidates.index(cid) + 1, 40),
            "rerank_score": round(float(s), 6),
        })
    return RetrievalResult(abstain=not chunks, chunks=chunks, stage_ms=stage,
                           degraded=degraded, candidates=candidates)
