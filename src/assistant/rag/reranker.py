"""Stage 3: cross-encoder reranker (design.md Gate 3).

Production model: BAAI/bge-reranker-v2-m3, scores passed through a sigmoid. The
lexical fallback (query-term coverage in [0, 1]) is used only when the model is
not loaded; results from it are flagged as degraded by the caller.
"""
from __future__ import annotations

import math
from typing import Protocol

from assistant.rag.bm25 import tokenize

_STOPWORDS = {"the", "and", "for", "with", "what", "how", "does", "are", "you", "your", "can", "this",
              "that", "from", "about", "which", "when", "where", "who", "is", "a", "an", "of", "to", "in", "on", "it"}


def lexical_rerank_score(query: str, text: str) -> float:
    q_terms = {t for t in tokenize(query) if len(t) > 1 and t not in _STOPWORDS}
    if not q_terms:
        return 0.0
    return len(q_terms & set(tokenize(text))) / len(q_terms)


class Reranker(Protocol):
    name: str
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", model=None) -> None:
        if model is None:
            from sentence_transformers import CrossEncoder
            model = CrossEncoder(model_name, max_length=512)
        self.model = model
        self.name = model_name

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        logits = self.model.predict([(query, t) for t in texts], show_progress_bar=False)
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]


class LexicalReranker:
    name = "lexical-fallback"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [lexical_rerank_score(query, t) for t in texts]
