# ADR-01 — Hybrid retrieval: RRF over weighted-score fusion
Status: Accepted (design.md § 1.7). Implemented in `src/assistant/rag/rrf.py`.
Decision: BM25 (k1 1.25, b 0.75) and dense (bge-large, FAISS HNSW) fused with RRF (k=60, pool=40), reranked to top 4 with threshold 0.42.
Why: rank-based fusion avoids per-query score normalization and has one parameter.
Current state: dense stage not built (reported as `dense_unavailable`); reranker is a lexical stand-in.
