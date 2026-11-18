"""Reciprocal Rank Fusion, k = 60, pool = 40 (design.md Gate 3, rank fusion)."""
from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60, pool: int = 40) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    fused = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return fused[:pool]
