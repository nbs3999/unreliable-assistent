"""Logic behind the Streamlit workbench. No Streamlit imports here, so it is testable.

Everything shown in the UI is computed from the running system or from files in the repo.
Nothing is hard-coded as a result.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from pathlib import Path

from assistant.api.pipeline import Deps, handle_query
from assistant.cache import build_key
from assistant.contracts import QueryRequest, ToolError, HybridRetrieveInput
from assistant.harness import ToolExecutionHarness
from assistant.harness.idempotency import IdempotencyStore
from assistant.ingress import run_pre_execution
from assistant.agents import classify
from assistant.contracts import Tier
from assistant.rag import BM25, KnowledgeBase, lexical_rerank_score, reciprocal_rank_fusion, tokenize
from assistant.rag.reranker import LexicalReranker

ROOT = Path(__file__).resolve().parents[3]


# ---------- Tab 1: architecture ----------

DESIGN_SECTIONS = ["1.1 System Charter", "1.2 MCP Tool", "1.3 Distributed Topology", "1.4 End-to-End Latency",
                   "1.5 KPI & SLA", "1.6 Failure Mode", "1.7 Architecture Decision", "8. Source Conflicts",
                   "9. Decisions"]


def design_checklist() -> list[dict]:
    text = (ROOT / "design.md").read_text(encoding="utf-8") if (ROOT / "design.md").exists() else ""
    rows = [{"item": f"design.md § {s}", "present": f"## {s}" in text} for s in DESIGN_SECTIONS]
    adr_dir = ROOT / "docs" / "adr"
    rows.append({"item": "ADR files (4)", "present": len(list(adr_dir.glob("ADR-*.md"))) == 4})
    rows.append({"item": "Gate 2 workflow image", "present": (ROOT / "docs" / "workflow_orchestration.png").exists()})
    rows.append({"item": "Golden evaluation set (39 queries)", "present": (ROOT / "eval/golden_set/golden.jsonl").exists()})
    rows.append({"item": "Red-team prompt set (15 prompts; design requires 100)",
                 "present": (ROOT / "red_team/prompts/smoke.jsonl").exists()})
    rows.append({"item": "MCP servers as separate processes", "present": False})
    rows.append({"item": "Graphify token pruning", "present": False})
    return rows


def triage_console(query: str) -> dict:
    result = classify(query)
    return {"route": result.route.value, "risk_tier": result.risk_tier.value, "confidence": result.confidence}


def ask(deps: Deps, query: str, tenant: str, user: str) -> tuple[object, list[dict]]:
    trace: list[dict] = []
    req = QueryRequest(request_id=str(uuid.uuid4()), tenant_id=tenant, user_id=user, query=query)
    response = handle_query(req, deps, trace=trace)
    return response, trace


# ---------- Tab 2: RAG lab (components computed here so the sliders apply) ----------

def rag_lab(deps: Deps, query: str, k1: float, b: float, rrf_k: int, threshold: float) -> dict:
    kb = deps.kb
    by_id = {c.chunk_id: c for c in kb.chunks}
    bm = BM25([tokenize(c.search_text) for c in kb.chunks], k1=k1, b=b)
    scores = bm.scores(tokenize(query))
    bm_order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i])[:50]
    lexical_ids = [kb.chunks[i].chunk_id for i in bm_order]

    cos: dict[str, float] = {}
    dense_ids: list[str] = []
    if deps.dense is not None:
        hits = deps.dense.search(query, top_k=50)
        dense_ids = [c for c, _ in hits]
        cos = dict(hits)

    rankings = [r for r in (lexical_ids, dense_ids) if r]
    fused = reciprocal_rank_fusion(rankings, k=rrf_k, pool=40)
    cands = [cid for cid, _ in fused]
    rr = deps.reranker
    rerank_name = rr.name if rr is not None else LexicalReranker.name
    rerank_scores = (rr or LexicalReranker()).score(query, [by_id[c].text for c in cands]) if cands else []

    rows = []
    for rrf_rank, (cid, s) in enumerate(zip(cands, rerank_scores), start=1):
        idx = next((i for i in bm_order if kb.chunks[i].chunk_id == cid), None)
        rows.append({
            "chunk_id": cid,
            "bm25": round(float(scores[idx]), 3) if idx is not None else 0.0,
            "cosine": round(cos.get(cid, float("nan")), 3) if cid in cos else None,
            "rrf_rank": rrf_rank,
            "rerank_score": round(float(s), 3),
            "passes_threshold": s >= threshold,
        })
    rows.sort(key=lambda r: -r["rerank_score"])
    return {"rows": rows[:20], "reranker": rerank_name, "dense_loaded": deps.dense is not None,
            "answered": any(r["passes_threshold"] for r in rows[:4])}


# ---------- Tab 3: MCP and plugins ----------

def mcp_status() -> list[dict]:
    cfg = json.loads((ROOT / "mcp_config.json").read_text(encoding="utf-8"))
    out = []
    for name, spec in cfg["mcpServers"].items():
        if spec.get("transport") == "stdio":
            script = next((a for a in spec.get("args", []) if a.endswith(".py")), None)
            implemented = bool(script) and (ROOT / script).exists()
            status = "implemented, not started" if implemented else "not implemented"
        else:
            status = "not running (no server listening)"
        out.append({"server": name, "transport": spec.get("transport"), "status": status})
    return out


def plugin_status() -> list[dict]:
    cfg = json.loads((ROOT / "mcp_config.json").read_text(encoding="utf-8"))
    return [{"plugin": p["name"], "stage": p["stage"], "fail_closed": p.get("fail_closed", False),
             "wired_to_pipeline": p["name"] in ("pii_redactor", "injection_shield")}
            for p in cfg["plugins"]]


def validate_payload(payload_json: str) -> dict:
    """Runs a hybrid_retrieve payload through the real harness (validation, repair, RBAC)."""
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"not JSON: {exc}"}
    harness = ToolExecutionHarness("retrieval", IdempotencyStore())
    try:
        out = harness.call(tool="hybrid_retrieve", tier=Tier.TIER_1_READ, model=HybridRetrieveInput,
                           payload=payload, handler=lambda m: m.model_dump(mode="json"))
        return {"ok": True, "validated": out.value, "repairs": out.repairs}
    except ToolError as exc:
        return {"ok": False, "error": exc.to_jsonrpc()}


# ---------- Tab 4: memory, vault, tokens ----------

def note_list(kb: KnowledgeBase) -> list[str]:
    return sorted({c.note_id for c in kb.chunks})


def note_text(kb: KnowledgeBase, note_id: str) -> str:
    return "\n\n".join(c.text for c in kb.chunks if c.note_id == note_id)


def token_estimate(text: str) -> int:
    """Rough estimate: ~1.3 tokens per word. Labeled as an estimate in the UI."""
    return round(len(re.findall(r"\S+", text)) * 1.3)


def token_savings(deps: Deps, query: str) -> dict:
    """Tokens in the cited passages vs. dumping every note that contains a candidate."""
    res = ask_retrieval_only(deps, query)
    cited_text = " ".join(c["text"] for c in res["chunks"])
    notes = {deps.kb.chunks[i].note_id for i, c in enumerate(deps.kb.chunks) if c.chunk_id in res["candidate_ids"]}
    dump_text = " ".join(note_text(deps.kb, n) for n in notes)
    cited, dump = token_estimate(cited_text), token_estimate(dump_text)
    return {"cited_tokens": cited, "raw_note_dump_tokens": dump,
            "saving_pct": round(100 * (1 - cited / dump), 1) if dump else 0.0}


def ask_retrieval_only(deps: Deps, query: str) -> dict:
    from assistant.rag import retrieve
    res = retrieve(deps.kb, query, dense=deps.dense, reranker=deps.reranker)
    return {"chunks": res.chunks, "candidate_ids": set(res.candidates)}


# ---------- Tab 5: red team and breaker ----------

def load_redteam(path: Path | None = None) -> list[dict]:
    path = path or ROOT / "red_team" / "prompts" / "smoke.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run_redteam(deps: Deps, items: list[dict], tenant: str) -> list[dict]:
    rows = []
    for item in items:
        guard = run_pre_execution(item["prompt"])
        req = QueryRequest(request_id=str(uuid.uuid4()), tenant_id=tenant, user_id="user_redteam",
                           query=item["prompt"])
        resp = handle_query(req, deps)
        if resp.status == "refused":
            actual = "refused"
        elif guard.redactions:
            actual = "redacted"
        else:
            actual = "not_refused"
        expect = item["expect"]
        if expect == "refused":
            passed = actual == "refused"
        elif expect == "redacted":
            passed = actual == "redacted"
        else:
            passed = actual != "refused"
        rows.append({"id": item["id"], "category": item["category"], "prompt": item["prompt"],
                     "expected": expect, "actual": actual, "status": resp.status,
                     "passed": passed, "reasons": guard.block_reasons})
    return rows


def cross_tenant_probe(deps: Deps) -> dict:
    """Stores a value under tenant A, then reads it as tenant B with the same query text."""
    key_a = build_key("tenant_acme", "user_probe", "probe query")
    deps.cache.set(key_a, "tenant_acme", "secret-for-acme")
    before = deps.cache.isolation_violations
    key_b = build_key("tenant_globex", "user_probe", "probe query")
    leaked = deps.cache.get(key_b, "tenant_globex")
    forced = deps.cache.get(key_a, "tenant_globex")  # same key, wrong tenant
    return {"keys_differ": key_a != key_b, "leak_on_own_key": leaked is not None,
            "leak_on_forced_key": forced is not None,
            "violations_counted": deps.cache.isolation_violations - before}


# ---------- Tab 6: scorecard and live latency ----------

def latency_run(deps: Deps, queries: list[str], tenant: str) -> list[dict]:
    rows = []
    for q in queries:
        t0 = time.perf_counter()
        resp, trace = ask(deps, q, tenant, "user_load")
        rows.append({"query": q, "status": resp.status,
                     "total_ms": round((time.perf_counter() - t0) * 1000, 2),
                     "stages": {k: v for k, v in resp.timings_ms.items()}})
    return rows


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return round(s[k], 2)


def golden_queries() -> list[str]:
    path = ROOT / "eval" / "golden_set" / "golden.jsonl"
    return [json.loads(l)["question"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def scorecard(report_dir: Path | None = None) -> list[dict]:
    """36 KPIs from design.md § 1.5. Only KPIs with a real measurement here get a value."""
    report_dir = report_dir or ROOT / "eval" / "reports"
    full = report_dir / "retrieval-full.json"
    lex = report_dir / "retrieval-lexical.json"
    rep = json.loads((full if full.exists() else lex).read_text())["summary"] if (full.exists() or lex.exists()) else {}
    backend = rep.get("backend", "none")
    measured = {
        "KPI-10": (rep.get("pool_recall_answerable"), 0.92, ">="),
        "KPI-11": (rep.get("precision_at_4"), 0.88, ">="),
        "KPI-12": (rep.get("mrr_at_4"), 0.85, ">="),
        "KPI-13": (rep.get("ndcg_at_4"), 0.86, ">="),
        "KPI-23": (rep.get("abstention_accuracy_negatives"), 0.98, ">="),
    }
    source_note = f"retrieval eval, backend={backend}, 39-query synthetic set; note-level proxy"
    names = {
        "KPI-01": ("Pre-hook guardrail latency p95", "<= 15 ms"),
        "KPI-02": ("PII redaction recall", ">= 99.8%"),
        "KPI-03": ("Prompt-injection block rate", ">= 99.5%"),
        "KPI-04": ("Triage routing accuracy", ">= 97%"),
        "KPI-05": ("Triage latency p95", "<= 25 ms"),
        "KPI-06": ("False-positive refusals", "<= 1%"),
        "KPI-07": ("BM25 latency p95", "<= 12 ms"),
        "KPI-08": ("Dense latency p95", "<= 25 ms"),
        "KPI-09": ("Cross-encoder latency p95", "<= 45 ms"),
        "KPI-10": ("Hybrid context recall", ">= 0.92"),
        "KPI-11": ("Context precision @4", ">= 0.88"),
        "KPI-12": ("MRR @4", ">= 0.85"),
        "KPI-13": ("nDCG @4", ">= 0.86"),
        "KPI-14": ("Tool first-pass validation", ">= 96%"),
        "KPI-15": ("Auto-repair success", ">= 90%"),
        "KPI-16": ("Infinite-loop escape", "100%"),
        "KPI-17": ("Mean ReAct steps", "<= 2.2"),
        "KPI-18": ("Context drift score", ">= 0.85"),
        "KPI-19": ("Tier 3 HITL enforcement", "100%"),
        "KPI-20": ("RAGAS faithfulness", ">= 0.92"),
        "KPI-21": ("RAGAS answer relevancy", ">= 0.90"),
        "KPI-22": ("RAGAS context entity recall", ">= 0.85"),
        "KPI-23": ("Unanswerable abstention", ">= 98%"),
        "KPI-24": ("Hallucination rate", "<= 0.5%"),
        "KPI-25": ("Time-to-first-token p95", "<= 180 ms"),
        "KPI-26": ("Prompt token reduction", ">= 45%"),
        "KPI-27": ("Semantic cache hit ratio", ">= 35%"),
        "KPI-28": ("Cross-tenant cache isolation", "100% (0 leaks)"),
        "KPI-29": ("Cost per 1,000 queries", "<= $0.45"),
        "KPI-30": ("MCP serialization p95", "<= 4 ms"),
        "KPI-31": ("E2E p50 @ 50K VUs", "<= 240 ms"),
        "KPI-32": ("E2E p95 @ 50K VUs", "<= 450 ms"),
        "KPI-33": ("E2E p99 @ 50K VUs", "<= 600 ms"),
        "KPI-34": ("HTTP 5xx @ 50K VUs", "<= 0.05%"),
        "KPI-35": ("Sustained throughput", ">= 8,500 RPS"),
        "KPI-36": ("RSS growth, 1-hr soak", "<= 3%"),
    }
    rows = []
    for kid in sorted(names, key=lambda k: int(k.split("-")[1])):
        name, target = names[kid]
        if kid in measured and measured[kid][0] is not None:
            value, threshold, _ = measured[kid]
            status = "PASS" if value >= threshold else "FAIL"
            rows.append({"KPI": kid, "name": name, "target": target, "value": round(value, 3),
                         "status": status, "source": source_note})
        else:
            rows.append({"KPI": kid, "name": name, "target": target, "value": None,
                         "status": "NOT MEASURED", "source": "no test or load run yet"})
    return rows
