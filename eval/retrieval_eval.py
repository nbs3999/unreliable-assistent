"""Retrieval evaluation over the golden set (design.md Gates 3 and 8, KPI-10 to KPI-13, KPI-23).

Usage:
  python eval/retrieval_eval.py --backend full      # bge-large + bge-reranker-v2-m3
  python eval/retrieval_eval.py --backend lexical   # BM25 only, no models

Relevance is judged at note level: a retrieved chunk is relevant if its note is in
`relevant_notes`. Empty `relevant_notes` marks an unanswerable query.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assistant.config import load_settings  # noqa: E402
from assistant.rag import CrossEncoderReranker, DenseIndex, KnowledgeBase, retrieve  # noqa: E402


def ndcg_at_4(relevances: list[int], n_relevant: int) -> float:
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(relevances[:4]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(n_relevant, 4)))
    return dcg / ideal if ideal else 0.0


def evaluate(backend: str, vault: Path, golden: Path) -> dict:
    s = load_settings()
    kb = KnowledgeBase.load(vault)
    dense = reranker = None
    if backend == "full":
        dense = DenseIndex([c.search_text for c in kb.chunks], [c.chunk_id for c in kb.chunks], s.embed_model)
        reranker = CrossEncoderReranker(s.rerank_model)
    note_of = {c.chunk_id: c.note_id for c in kb.chunks}

    rows = []
    for line in golden.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        relevant = set(item["relevant_notes"])
        t0 = time.perf_counter()
        res = retrieve(kb, item["question"], dense=dense, reranker=reranker)
        latency = (time.perf_counter() - t0) * 1000

        returned = [note_of[c["chunk_id"]] for c in res.chunks]
        rel_flags = [1 if n in relevant else 0 for n in returned]
        # nDCG counts each relevant note once: extra chunks from the same note are not new evidence
        seen, ndcg_flags = set(), []
        for n in returned:
            hit = n in relevant and n not in seen
            ndcg_flags.append(1 if hit else 0)
            if hit: seen.add(n)
        pool_hit = any(note_of[cid] in relevant for cid in res.candidates)
        precision4 = sum(rel_flags) / 4 if rel_flags else 0.0
        mrr4 = next((1 / (i + 1) for i, f in enumerate(rel_flags) if f), 0.0)
        ndcg4 = ndcg_at_4(ndcg_flags, len(relevant)) if relevant else 0.0
        answered = not res.abstain
        if relevant:
            correct_decision = answered
        else:
            correct_decision = not answered
        rows.append({"id": item["id"], "category": item["category"], "answerable": bool(relevant),
                     "pool_recall": 1.0 if (relevant and pool_hit) else 0.0,
                     "precision_at_4": precision4, "mrr_at_4": mrr4, "ndcg_at_4": ndcg4,
                     "abstained": res.abstain, "decision_correct": correct_decision,
                     "returned_notes": returned, "latency_ms": round(latency, 2),
                     "degraded": res.degraded})

    def mean(values):
        return round(sum(values) / len(values), 4) if values else None

    answerable = [r for r in rows if r["answerable"]]
    negatives = [r for r in rows if not r["answerable"]]
    summary = {
        "backend": backend,
        "queries": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(negatives),
        "pool_recall_answerable": mean([r["pool_recall"] for r in answerable]),
        "precision_at_4": mean([r["precision_at_4"] for r in answerable]),
        "mrr_at_4": mean([r["mrr_at_4"] for r in answerable]),
        "ndcg_at_4": mean([r["ndcg_at_4"] for r in answerable]),
        "abstention_accuracy_negatives": mean([r["decision_correct"] for r in negatives]),
        "decision_accuracy_all": mean([r["decision_correct"] for r in rows]),
        "latency_ms_p95": round(sorted(r["latency_ms"] for r in rows)[int(0.95 * (len(rows) - 1))], 2),
        "degraded": sorted({d for r in rows for d in r["degraded"]}),
    }
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    summary["by_category_decision_accuracy"] = {c: mean([r["decision_correct"] for r in v]) for c, v in by_cat.items()}
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["full", "lexical"], default="full")
    ap.add_argument("--vault", type=Path, default=ROOT / "knowledge_vault")
    ap.add_argument("--golden", type=Path, default=ROOT / "eval" / "golden_set" / "golden.jsonl")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    report = evaluate(args.backend, args.vault, args.golden)
    out = args.out or ROOT / "eval" / "reports" / f"retrieval-{args.backend}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
