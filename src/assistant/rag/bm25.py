"""BM25Okapi, k1=1.25, b=0.75 (design.md Gate 3, stage 1). Pure Python, no stemmer."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(token: str) -> str:
    """Light suffix stripper (stand-in for Porter, Gate 3). Leaves codes like '099' alone."""
    if token.isdigit() or len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower())]


class BM25:
    def __init__(self, documents: list[list[str]], k1: float = 1.25, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(documents)
        self.doc_len = [len(d) for d in documents]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in documents]
        df: Counter[str] = Counter()
        for counts in self.tf:
            df.update(counts.keys())
        self.idf = {t: math.log((self.n - n + 0.5) / (n + 0.5) + 1.0) for t, n in df.items()}

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, counts in enumerate(self.tf):
                f = counts.get(term, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1.0))
                out[i] += idf * f * (self.k1 + 1) / denom
        return out
