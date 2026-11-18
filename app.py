"""The Unreliable Assistant — developer workbench (design.md Gate 18).

Run:  streamlit run app.py
Six tabs, each reads live state from the running system or from repo files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from assistant.api.app import build_deps  # noqa: E402
from assistant.workbench import services as svc  # noqa: E402

st.set_page_config(page_title="The Unreliable Assistant — Workbench", layout="wide")


@st.cache_resource(show_spinner="Loading knowledge base and models (first start can take a minute)…")
def get_deps():
    return build_deps()


deps = get_deps()
st.title("The Unreliable Assistant — Developer Workbench")
st.caption(f"Retrieval backend: {'full (bge-large + bge-reranker-v2-m3)' if deps.dense else 'lexical (BM25 only)'} · "
           f"vault chunks: {len(deps.kb.chunks)} · tenants: {', '.join(deps.allowed_tenants)}")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "1 · Architecture & workflow", "2 · RAG lab", "3 · MCP & plugins",
    "4 · Memory & tokens", "5 · Red team & breaker", "6 · KPI scorecard & load",
])

# ---------------- Tab 1 ----------------
with tab1:
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Design contract checklist")
        st.dataframe(svc.design_checklist(), width="stretch", hide_index=True)
        st.subheader("Triage console")
        q = st.text_input("Query to classify", "Verify batch LOT-88392 safety protocol and return triage status",
                          key="triage_q")
        st.json(svc.triage_console(q))
    with right:
        st.subheader("Workflow (Gate 2)")
        img = ROOT / "docs" / "workflow_orchestration.png"
        if img.exists():
            st.image(str(img), width="stretch")
        else:
            st.warning("docs/workflow_orchestration.png not found")

    st.subheader("Ask the assistant (live pipeline + ReAct trace)")
    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Question", "What is the returns policy for refunds?", key="ask_q")
    tenant = c2.selectbox("Tenant", list(deps.allowed_tenants), key="ask_tenant")
    user = c3.text_input("User ID", "user_wb", key="ask_user")
    if st.button("Run query", type="primary"):
        try:
            resp, trace = svc.ask(deps, query, tenant, user)
            st.session_state["last_trace"] = trace
            st.session_state["last_resp"] = resp.model_dump(mode="json")
        except Exception as exc:  # surfaced to the user, not swallowed
            st.error(f"{type(exc).__name__}: {exc}")
    if "last_resp" in st.session_state:
        r = st.session_state["last_resp"]
        st.markdown(f"**Route:** `{r['route']}` · **Status:** `{r['status']}` · **Mode:** `{r['mode']}`")
        st.info(r["answer"])
        if r["sources"]:
            st.write("Cited chunks:", [s["chunk_id"] for s in r["sources"]])
        if r["degraded"]:
            st.warning(f"Degraded: {', '.join(r['degraded'])}")
        with st.expander("Step trace", expanded=True):
            for step in st.session_state.get("last_trace", []):
                st.json(step, expanded=False)

    st.subheader("Tier 3 HITL approval queue")
    pending = [p for p in deps.hitl.all() if p.status == "PENDING_APPROVAL"]
    if not pending:
        st.caption("No pending approvals. Queries such as 'submit the refund request' create one.")
    for p in pending:
        cols = st.columns([3, 1, 1])
        cols[0].write(f"`{p.approval_id}` · {p.action} · tenant `{p.tenant_id}`")
        reviewer = st.session_state.get("reviewer", "reviewer_wb")
        if cols[1].button("Approve", key=f"ap_{p.approval_id}"):
            deps.hitl.decide(p.approval_id, reviewer, approve=True)
            st.rerun()
        if cols[2].button("Reject", key=f"rj_{p.approval_id}"):
            deps.hitl.decide(p.approval_id, reviewer, approve=False)
            st.rerun()
    decided = [p for p in deps.hitl.all() if p.status != "PENDING_APPROVAL"]
    if decided:
        st.caption("Decided")
        st.dataframe([{"approval_id": p.approval_id, "status": p.status, "reviewer": p.reviewer,
                       "tenant": p.tenant_id} for p in decided], hide_index=True, width="stretch")

# ---------------- Tab 2 ----------------
with tab2:
    st.subheader("3-stage hybrid RAG lab")
    st.caption("Sliders recompute BM25, RRF, and threshold on the fly. Scores are computed here, not cached.")
    s1, s2, s3, s4 = st.columns(4)
    k1 = s1.slider("BM25 k1", 0.0, 3.0, 1.25, 0.05)
    b = s2.slider("BM25 b", 0.0, 1.0, 0.75, 0.05)
    rrf_k = s3.slider("RRF k", 1, 120, 60)
    threshold = s4.slider("Rerank threshold", 0.0, 1.0, 0.42, 0.01)
    lab_q = st.text_input("Query", "How long is the warranty on valves?", key="lab_q")
    if lab_q.strip():
        lab = svc.rag_lab(deps, lab_q, k1, b, rrf_k, threshold)
        st.caption(f"Reranker: {lab['reranker']} · dense stage loaded: {lab['dense_loaded']} · "
                   f"answer would pass threshold: {lab['answered']}")
        st.dataframe(lab["rows"], width="stretch", hide_index=True)

# ---------------- Tab 3 ----------------
with tab3:
    st.subheader("MCP servers (from mcp_config.json)")
    st.dataframe(svc.mcp_status(), width="stretch", hide_index=True)
    st.subheader("Plugins")
    st.caption("Fail-closed plugins are locked. Toggles are shown only where a plugin is wired to the pipeline.")
    for p in svc.plugin_status():
        cols = st.columns([2, 2, 1, 2])
        cols[0].write(f"**{p['plugin']}**")
        cols[1].write(p["stage"])
        cols[2].write("locked" if p["fail_closed"] else "")
        if p["fail_closed"]:
            cols[3].checkbox("enabled", value=True, disabled=True, key=f"pl_{p['plugin']}")
        else:
            cols[3].caption("not wired to pipeline yet; no toggle" if not p["wired_to_pipeline"] else "wired")
    st.subheader("JSON-RPC payload inspector (hybrid_retrieve)")
    st.caption("Runs the payload through the real harness: strict validation, auto-repair, RBAC.")
    example = {"request_id": "3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f", "tenant_id": "tenant_acme",
               "query": "pressure valve SKU99", "top_k": 50}
    payload_text = st.text_area("Payload", json.dumps(example, indent=2), height=180)
    if st.button("Validate payload"):
        st.json(svc.validate_payload(payload_text))

# ---------------- Tab 4 ----------------
with tab4:
    st.subheader("Knowledge vault viewer")
    notes = svc.note_list(deps.kb)
    note = st.selectbox("Note", notes)
    st.text(svc.note_text(deps.kb, note))
    st.subheader("Token savings (estimate)")
    tq = st.text_input("Query for token comparison", "What is the returns policy for refunds?", key="tok_q")
    if tq.strip():
        ts = svc.token_savings(deps, tq)
        a, b2, c = st.columns(3)
        a.metric("Tokens in cited passages", ts["cited_tokens"])
        b2.metric("Tokens if whole notes were sent", ts["raw_note_dump_tokens"])
        c.metric("Estimated saving", f"{ts['saving_pct']}%", help="KPI-26 target: ≥ 45%. Estimate, ~1.3 tokens/word.")
    st.subheader("Session cache browser (values never shown)")
    st.dataframe(deps.cache.snapshot(), width="stretch", hide_index=True)
    st.subheader("Audit log (hash chain)")
    entries = deps.audit.entries()
    st.metric("Entries", len(entries), help="Verified on each render. Query text is never stored, only digests.")
    st.write("Chain verifies:", "✅ yes" if deps.audit.verify() else "❌ BROKEN")
    st.dataframe([{"seq": e["seq"], "route": e["payload"].get("route"), "status": e["payload"].get("status"),
                   "tenant": e["payload"].get("tenant_id"), "hash": e["hash"][:16] + "…"} for e in entries[-50:]],
                 width="stretch", hide_index=True)
    st.subheader("Graphify")
    st.info("Graphify subgraph pruning is not built yet (Gate 17 / mcp-graphify-vault). Token figures above are for cited passages only.")

# ---------------- Tab 5 ----------------
with tab5:
    st.subheader("Red-team smoke suite")
    items = svc.load_redteam()
    st.caption(f"{len(items)} prompts loaded from red_team/prompts/smoke.jsonl. The design requires 100; this is a starting set.")
    if st.button("Run red-team suite", type="primary"):
        st.session_state["rt"] = svc.run_redteam(deps, items, deps.allowed_tenants[0])
    rt = st.session_state.get("rt")
    if rt:
        passed = sum(r["passed"] for r in rt)
        st.metric("Passed", f"{passed} / {len(rt)}")
        st.dataframe(rt, width="stretch", hide_index=True)
        fails = [r for r in rt if not r["passed"]]
        if fails:
            st.error("Failing: " + ", ".join(f"{f['id']} ({f['category']}: expected {f['expected']}, got {f['actual']})" for f in fails))
    st.subheader("Cross-tenant cache probe")
    if st.button("Run cross-tenant probe"):
        st.json(svc.cross_tenant_probe(deps))
    st.subheader("Circuit breaker")
    st.caption("Breaker state is per process. It opens after 2 identical failing tool calls.")
    st.dataframe(deps.harness.breaker.snapshot() or [{"state": "no failures recorded"}], hide_index=True,
                 width="stretch")
    if st.button("Reset breaker"):
        deps.harness.breaker.reset()
        st.rerun()

# ---------------- Tab 6 ----------------
with tab6:
    st.subheader("36-KPI scorecard")
    st.caption("PASS/FAIL only where a measurement exists in this repo. Everything else is marked NOT MEASURED.")
    rows = svc.scorecard()
    measured = [r for r in rows if r["status"] != "NOT MEASURED"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Measured", f"{len(measured)} / {len(rows)}")
    m2.metric("Passing", sum(r["status"] == "PASS" for r in rows))
    m3.metric("Failing", sum(r["status"] == "FAIL" for r in rows))
    st.dataframe(rows, width="stretch", hide_index=True)

    st.subheader("Live latency run")
    n = st.slider("Queries from the golden set", 5, 39, 20)
    if st.button("Run latency check"):
        with st.spinner("Running queries through the pipeline…"):
            st.session_state["lat"] = svc.latency_run(deps, svc.golden_queries()[:n], deps.allowed_tenants[0])
    lat = st.session_state.get("lat")
    if lat:
        totals = [r["total_ms"] for r in lat]
        p1, p2, p3 = st.columns(3)
        p1.metric("p50 total", f"{svc.percentile(totals, 50)} ms")
        p2.metric("p95 total", f"{svc.percentile(totals, 95)} ms", help="Gate: ≤ 450 ms end to end (single user, not 50K VUs)")
        p3.metric("p99 total", f"{svc.percentile(totals, 99)} ms")
        st.bar_chart({"total_ms": totals})
        st.caption("Single-process, single-user timings. The 50K-VU load test is not built.")
        st.dataframe(lat, width="stretch", hide_index=True)
