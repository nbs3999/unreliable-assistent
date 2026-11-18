# ADR-02 — Reranker: ONNX FP16; INT8 only on evidence
Status: Accepted, implementation pending (Phase 3).
Decision: bge-reranker-v2-m3 in FP16, batch 32, max_len 512. INT8 only if KPI-09 fails and RAGAS gates still pass.
Current state: `src/assistant/rag/reranker.py` is a query-term-coverage stand-in, not calibrated; do not treat its scores as relevance.
