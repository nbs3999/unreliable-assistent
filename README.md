# The Unreliable Assistant — Enterprise Agentic Platform

An enterprise AI assistant that answers staff and customer questions from company policies, SOPs, and product catalogs, and carries out workflow actions only with human approval. It is a rebuild of an earlier prototype that hallucinated facts, looped on tool calls, leaked cache data between users, and collapsed under load.

**Status: Phase 2 foundations built and tested (68 tests passing).** Contracts, tool harness, bounded loop, ingress guards, cache, triage, a hybrid RAG library, governance, and the API are implemented. The dense retriever, the neural reranker, the LLM generator, the MCP servers as separate processes, and the Streamlit workbench are not yet built. See *Current status* below.

| Document | Purpose |
|---|---|
| [design.md](design.md) | Architecture contract: charter, tool schemas, latency budget, 36 KPIs, FMEA, ADRs, decisions |
| [workflow.md](workflow.md) | Build phases with exit checks, runtime flow, development process |
| [docs/workflow_orchestration.png](docs/workflow_orchestration.png) | Gate 2 workflow diagram (rendered from Graphviz) |
| [docs/adr/](docs/adr/) | Architecture Decision Records (ADR-01 to ADR-04) |

Read `design.md` before changing any behavior. Read `workflow.md` before starting a phase.

---

## What it does

A request to `POST /api/v1/agent/query` goes through these steps:

1. **Ingress:** PII redaction and prompt-injection checks. Both fail closed.
2. **Cache:** semantic cache lookup, keyed per tenant and user.
3. **Triage:** a deterministic classifier routes the request to one of four paths: `DIRECT_ANSWER`, `HYBRID_RAG`, `TRANSACTION_EXEC`, or `REJECT_OOS`.
4. **Retrieval:** BM25 and dense search, fused with Reciprocal Rank Fusion, reranked by a cross-encoder. The answer is written only from the top passages. If nothing scores above 0.42, the system abstains.
5. **Actions:** any state-changing action writes a pending approval record. A human approves or rejects it before anything executes.
6. **Verification:** every claim is checked against the cited passages. RAGAS scores run asynchronously after the response.

## Non-negotiable constraints

- p95 latency ≤ 450 ms and p99 ≤ 600 ms at 50,000 concurrent users.
- Strict tenant isolation in every database query and every cache key.
- No raw personal data in logs, cache, traces, or stored facts.
- No clinical, financial, or legal action without human approval.
- Every agent loop terminates (max 5 iterations, 380 ms budget).

---

## Project structure

```
.
├── README.md                    This file
├── design.md                    Architecture contract (read first)
├── workflow.md                  Build phases and development process
├── pyproject.toml               Python project and dependencies
├── mcp_config.json              MCP servers and plugin registration
├── app.py                       Streamlit developer workbench (6 tabs)
│
├── src/assistant/               Application package (the core system)
│   ├── api/                     FastAPI app, routes, dependencies
│   │   └── routes/              agent.py (query endpoint), hitl.py, health.py
│   ├── ingress/                 Pre-execution hooks: pii_redactor, injection_shield
│   ├── cache/                   Redis semantic cache, key builder (tenant:user:query)
│   ├── agents/                  triage.py, retrieval.py, execution.py, verification.py
│   ├── loop/                    Bounded ReAct state machine, GoalAnchorBlock,
│   │                            observation compression, session memory
│   ├── harness/                 ToolExecutionHarness: validation, auto-repair,
│   │                            RBAC tiers, idempotency, circuit breaker
│   ├── plugins/                 Pluggy hookspecs and the plugin registry
│   ├── contracts/               Pydantic v2 models and JSON-RPC error codes
│   │                            (the single source for tool schemas)
│   ├── rag/                     BM25, RRF, reranker stand-in, vault loader, hybrid retrieve
│   ├── api/                     FastAPI app (app.py) and request pipeline (pipeline.py)
│   ├── llm/                     LLM client with timeouts and 429 handling
│   ├── observability/           OpenTelemetry tracing and Prometheus metrics
│   ├── governance/              Hash-chained audit log, tenant-scoped repository
│   └── config/                  Typed settings (env-driven)
│
├── mcp_servers/                 MCP JSON-RPC servers (separate processes)
│   ├── hybrid_rag/              server.py: hybrid_retrieve tool, rag:// resources
│   ├── graphify_vault/          server.py: graph_subgraph tool, vault:// resources
│   └── state_store/             server.py: session facts, HITL, audit (HTTP)
│
│
├── knowledge_vault/             Obsidian notes (source of truth for knowledge)
│   ├── policies/                One atomic note per policy, with frontmatter
│   ├── sops/                    Standard operating procedures
│   └── catalog/                 Product catalog notes (SKU/LOT entries)
├── docs/source/                 The two original source documents (.docx)
├── graph/                       graph.json generated by graphify (gitignored)
│
├── eval/                        Quality measurement (runs in CI)
│   ├── golden_set/              250 labeled questions (stratified 25/25/20/15/15)
│   ├── ragas/                   RAGAS runner and release-gate checks
│   ├── ir_metrics/              Recall@50, MRR@4, nDCG@4
│   └── scorecard/               Generates the 36-KPI pass/fail report from raw output
│
├── red_team/
│   ├── prompts/                 100 adversarial prompts in 5 categories
│   └── runner.py                Runs the suite, writes the attack log
│
├── load_tests/
│   ├── k6_50k_load.js           Grafana k6 script (50K VUs)
│   └── jmeter_50k_plan.jmx      JMeter controller/worker plan
│
├── deploy/
│   ├── docker-compose.yml       Local stack: API, Redis, Postgres, MCP servers
│   ├── otel/                    OpenTelemetry Collector config
│   ├── prometheus/              Scrape config and alert rules (warn 400 / page 450 ms)
│   └── grafana/                 Dashboards
│
├── docs/
│   ├── workflow_orchestration.png
│   └── adr/                     One file per architecture decision
│
├── tests/
│   ├── unit/                    Pure logic: harness, repair rules, state machine
│   ├── contract/                Schemas match design.md § 1.2 (CI fails on drift)
│   ├── integration/             API + MCP servers + Redis + Postgres
│   ├── chaos/                   Loop escape, breaker, dependency failures (KPI-16)
│   └── tenancy/                 Cross-tenant probes, key-prefix checks (KPI-28)
│
├── scripts/                     Developer tasks: build index, build graph, sign manifests
└── .github/workflows/ci.yml     Pipeline stages in the order given in workflow.md § C.2
```

### Layout rules

These rules keep the structure from degrading as the code grows.

1. **Dependency direction.** `api → agents → harness → contracts`. `mcp_servers` may import `contracts` and `rag`, but never `api`, `agents`, or `loop`. Nothing imports from `tests`.
2. **Contracts are the single source of truth.** Tool schemas live only in `src/assistant/contracts/`. Client and server both import them. The contract test fails if the generated JSON Schema differs from `design.md § 1.2`.
3. **Tenancy is enforced in one place.** All database and cache access goes through `governance/` repositories and `cache/`. Code that builds a query or key by hand fails the tenancy tests.
4. **Each MCP server is its own process** with its own bulkhead pool. The API never opens a database connection for a tool; it calls the MCP server.
5. **Plugins are registered, not imported.** Core code calls hook specs. Plugins are loaded from `mcp_config.json` and verified at startup. Fail-closed plugins cannot be disabled in production.
6. **Generated artifacts are not hand-edited.** `graph/`, the scorecard output, and JSON Schemas come from scripts in `scripts/` or `eval/`.
7. **Each KPI has a test directory or eval directory.** A KPI without a home in `tests/` or `eval/` is not measured, so it cannot pass.

---

## Current status

| Area | State |
|---|---|
| Contracts (Pydantic v2, strict, error codes) | Built, tested |
| Tool execution harness (validate, repair, RBAC, idempotency, breaker) | Built, tested |
| Bounded ReAct state machine (budgets, iteration cap) | Built, tested |
| Ingress guards (PII, injection; fail closed) | Built, tested (regex; Presidio planned) |
| Semantic cache (tenant-scoped key, tenant re-check, jittered TTL) | Built, tested (in-process; Redis planned) |
| Triage (deterministic) | Built, tested (rules; classifier planned) |
| RAG: BM25, RRF, knowledge loader, retrieval | Built, tested (dense stage and neural reranker missing) |
| Governance: hash-chained audit, Tier 3 HITL store | Built, tested (in-memory; Postgres planned) |
| API: `POST /api/v1/agent/query`, `GET /health` | Built, tested |
| Streamlit workbench (`app.py`, six tabs per design Gate 18) | Built; smoke-tested headlessly |
| Answer generation | Extractive only: the top cited passage, no LLM |
| MCP servers as separate processes | Not built (`mcp_servers/` is a placeholder) |
| Eval harness (retrieval, 39 queries), red-team smoke (15 prompts) | Built; results in the workbench |
| Load tests (50K VUs), observability stack, Graphify pruning | Not built |

## Running

### Setup (once)

```bash
cd unreliable-assistant
pip install -e ".[dev,ui]"       # dev = tests, ui = Streamlit workbench
pytest -q                      # optional: run the test suite (73 tests)
```

### Start the backend (API)

```bash
uvicorn assistant.api.app:app --app-dir src --port 8000
```

- API docs (try requests in the browser): http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Start the UI (workbench)

Run this in a second terminal, with the backend still running:

```bash
streamlit run app.py --server.port 8501
```

- Open http://localhost:8501

The UI runs its own copy of the pipeline. It does not call the API server, so its approval queue and cache are separate from the backend's.

### Faster start (BM25 only, no models)

The default retrieval loads the bge-large embedding model and the bge-reranker cross-encoder. On first start this takes minutes on CPU. To skip the models, set `RETRIEVAL_BACKEND=lexical` before either command:

```bash
RETRIEVAL_BACKEND=lexical uvicorn assistant.api.app:app --app-dir src --port 8000
RETRIEVAL_BACKEND=lexical streamlit run app.py --server.port 8501
```

### Troubleshooting

- Port already in use: pick another port, for example `--port 8001` or `--server.port 8502`.
- `ModuleNotFoundError: assistant`: run the command from the `unreliable-assistant` folder, and keep `--app-dir src` for uvicorn.
- Workbench shows a missing file error: make sure `mcp_config.json` and `knowledge_vault/` exist in the project folder.

Example:

```bash
curl -s localhost:8000/api/v1/agent/query -H 'Content-Type: application/json' \
  -d '{"request_id":"3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f","tenant_id":"tenant_acme","user_id":"user_7","query":"What is the returns policy?"}'
```

Configuration (environment variables): `VAULT_DIR` (default `knowledge_vault/`), `ALLOWED_TENANTS` (default `tenant_acme`).

## Workbench

`streamlit run app.py` opens six tabs: architecture and HITL queue, RAG lab with live sliders, MCP and plugin inspector with the real validator, memory and token estimates, red team and circuit breaker, and the KPI scorecard with a live latency run. The workbench runs the pipeline in its own process, so its approval queue and cache are separate from a running API server.

## Known gaps versus design.md

- The lexical reranker and light stemmer are stand-ins. Retrieval quality is not measured yet, so KPI-10 to KPI-13 are unverified.
- Without an LLM, answers are passages, not generated text. Faithfulness is therefore trivially high here, but answers are less readable.
- The API runs in one process with in-memory cache, audit, and HITL state. Nothing survives a restart.
- Latency and load KPIs are unmeasured. The 36-KPI scorecard does not exist yet.

## Conventions

- Python 3.11+, FastAPI, Pydantic v2 with `strict=True`.
- Commits and PRs follow the rules in `workflow.md` § C.1.
- A change to any number in `design.md` requires an ADR in `docs/adr/`.
