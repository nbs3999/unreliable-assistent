# The Unreliable Assistant — Enterprise Agentic Platform

An enterprise AI assistant that answers staff and customer questions from company policies, SOPs, and product catalogs, and carries out workflow actions only with human approval. It is a rebuild of an earlier prototype that hallucinated facts, looped on tool calls, leaked cache data between users, and collapsed under load.

**Status: Phase 2 foundations built and tested (94 tests passing).** API-key authentication with tenant/user binding and a reviewer-only approval API are in place. Contracts, tool harness, bounded loop, ingress guards, cache, triage, a hybrid RAG library, governance, the API, and the Streamlit workbench are implemented. The neural retrieval path (dense index and cross-encoder) is implemented but misses its latency budget on CPU. An optional, pluggable LLM is supported (off by default; generated answers are unverified for faithfulness). The MCP servers as separate processes are not built. See *Current status* below, [gaps.md](gaps.md) for open gaps, and [deployment.md](deployment.md) to deploy.

| Document | Purpose |
|---|---|
| [design.md](design.md) | Architecture contract: charter, tool schemas, latency budget, 36 KPIs, FMEA, ADRs, decisions |
| [workflow.md](workflow.md) | Build phases with exit checks, runtime flow, development process |
| [docs/workflow_orchestration.png](docs/workflow_orchestration.png) | Gate 2 workflow diagram (rendered from Graphviz) |
| [docs/adr/](docs/adr/) | Architecture Decision Records (ADR-01 to ADR-04) |
| [deployment.md](deployment.md) | Deployment guide: what runs, API keys, configuration, container build |
| [gaps.md](gaps.md) | Implementation gap analysis against design.md and the Audit |

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
├── gaps.md                      Implementation gap analysis against design.md and the Audit
├── deployment.md                Deployment guide: what runs, API keys, configuration, container build
├── Dockerfile                   API service image (Streamlit not included)
├── pyproject.toml               Python project and dependencies
├── mcp_config.json              MCP server and plugin registration (servers not yet built)
├── app.py                       Streamlit developer workbench (6 tabs, not deployed)
│
├── src/assistant/               Application package (the core system)
│   ├── api/                     app.py (routes), pipeline.py (request flow), auth.py (API keys)
│   ├── ingress/                 PII redaction and injection screen (regex, fail closed)
│   ├── cache/                   Semantic cache, key builder (tenant:user:query), in-process
│   ├── agents/                  triage.py (deterministic routing)
│   ├── loop/                    Bounded ReAct state machine and budgets
│   ├── harness/                 ToolExecutionHarness: validation, repair, RBAC, idempotency, breaker
│   ├── rag/                     BM25, dense index, RRF, cross-encoder reranker, hybrid retrieve
│   ├── contracts/               Pydantic v2 models and JSON-RPC error codes
│   ├── governance/              Hash-chained audit log, in-memory HITL store
│   ├── workbench/               Services behind the Streamlit tabs
│   ├── config/                  Typed settings (env-driven)
│   ├── llm/                     Pluggable LLM providers (off by default; OpenAI-compatible client)
│   ├── observability/           (planned, empty)
│   └── plugins/                 (planned, empty)
│
├── mcp_servers/                 (planned, empty): MCP servers as separate processes
│
├── knowledge_vault/             Obsidian notes (policies, SOPs, catalog); source of truth for knowledge
├── docs/                        Workflow diagram, ADRs (docs/adr/), source documents (docs/source/)
├── graph/                       Reserved for graph.json (gitignored; Graphify not built)
│
├── eval/                        Quality measurement
│   ├── retrieval_eval.py        IR evaluation over the golden set (writes eval/reports/)
│   ├── golden_set/              Labeled questions (39 today; target 250)
│   ├── reports/                 Retrieval eval outputs
│   └── ragas/, ir_metrics/, scorecard/   (planned, empty)
│
├── red_team/prompts/            smoke.jsonl (15 prompts; target 100). No runner yet.
├── load_tests/                  (planned, empty): k6 and JMeter scripts
├── deploy/                      (planned, empty): OTel, Prometheus, Grafana configs
├── scripts/make_api_key.py      Issue client and reviewer API keys (stores digests only)
│
├── tests/
│   ├── unit/                    Pure logic: harness, repair, state machine, RAG, ingress
│   ├── contract/                Pydantic contracts
│   ├── integration/             API end to end (auth, approvals, injection, budget)
│   ├── chaos/                   Loop escape and terminal-state checks (KPI-16)
│   └── tenancy/                 Cross-tenant cache isolation (KPI-28)
│
└── .github/workflows/ci.yml     Clean install, tests, secret scan, container build
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
| RAG: BM25, RRF, knowledge loader, retrieval | Built, tested. Dense and cross-encoder stages built; the full backend misses the latency budget on CPU (see Running) |
| Governance: hash-chained audit, Tier 3 HITL store | Built, tested (in-memory; Postgres planned) |
| API: `POST /api/v1/agent/query`, `GET /health`, reviewer HITL routes | Built, tested. API-key auth with tenant/user binding |
| Streamlit workbench (`app.py`, six tabs per design Gate 18) | Built; smoke-tested headlessly |
| Answer generation | Extractive by default. Optional pluggable OpenAI-compatible LLM (`LLM_PROVIDER`), with citation check and fallback. Faithfulness not yet measured |
| MCP servers as separate processes | Not built (`mcp_servers/` is a placeholder) |
| Eval harness (retrieval, 39 queries), red-team smoke (15 prompts) | Built; results in the workbench |
| Load tests (50K VUs), observability stack, Graphify pruning | Not built |

## Running

### Setup (once)

```bash
cd unreliable-assistant
pip install -e ".[dev,models,ui]"  # dev = tests, models = neural retrieval, ui = Streamlit workbench (dev only)
pytest -q                      # run the test suite (94 tests)
```

### Start the backend (API)

The API needs a keys file before it accepts queries. Create one with `python scripts/make_api_key.py --keys-file api_keys.json --tenant tenant_acme --user user_1` and set `export API_KEYS_FILE=$PWD/api_keys.json`. See [deployment.md](deployment.md).

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

## Getting started

Pick one path. Each one needs the API key setup in the next section.

### A. Clone and run locally

```bash
git clone https://github.com/nbs3999/unreliable-assistent.git
cd unreliable-assistent

python3.11 -m venv .venv && source .venv/bin/activate
# CPU-only torch first, so pip does not download the multi-GB CUDA build:
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev,models]"          # models = neural retrieval. Drop ",models" for lexical-only.
pytest -q                               # 94 tests; no models or network needed
```

Run the API. Use `lexical` for the fast path (no retrieval models); use `full` for neural retrieval (needs the `models` extra and about 2 GB for model weights, slow on CPU):

```bash
python scripts/make_api_key.py --keys-file api_keys.json --tenant tenant_acme --user user_1
export API_KEYS_FILE=$PWD/api_keys.json ALLOWED_TENANTS=tenant_acme
export RETRIEVAL_BACKEND=lexical
uvicorn assistant.api.app:app --app-dir src --port 8000 --workers 1
```

Then call it with the key the script printed:

```bash
curl -s localhost:8000/api/v1/agent/query -H "Authorization: Bearer $CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{"request_id":"3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f","tenant_id":"tenant_acme","user_id":"user_1","query":"What is the returns policy for refunds?"}'
```

The Streamlit workbench is a developer tool, not part of the API. Run it in a second terminal with `pip install -e ".[ui]"` and `streamlit run app.py`. It runs its own pipeline, so its approvals and cache are separate from the API's.

### B. Run the Docker image

The image contains the API, the knowledge vault, and the LLM client. It does not contain models or keys. Build it from the repo (no public registry is published yet):

```bash
docker build -t unreliable-assistant:0.2.0 .
```

Or, if someone else built it, load the saved file:

```bash
docker load -i unreliable-assistant-0.2.0.tar.gz     # created with: docker save unreliable-assistant:0.2.0 | gzip > unreliable-assistant-0.2.0.tar.gz
```

Run it. The keys file is mounted read-only and never copied into the image:

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -e API_KEYS_FILE=/run/secrets/api_keys.json -e RETRIEVAL_BACKEND=lexical \
  -v "$PWD/api_keys.json:/run/secrets/api_keys.json:ro" \
  unreliable-assistant:0.2.0
```

To use a local model from the container, see "Choose a model" below. On Linux, the container reaches the host through `host.docker.internal`, so add `--add-host=host.docker.internal:host-gateway` and point `LLM_BASE_URL` there.

For production deployment (keys, the one-replica constraint, configuration), see [deployment.md](deployment.md).

### Choose a model

The API answers in one of three ways. Pick one with environment variables. No code changes are needed.

| Mode | Set | Answers | Needs |
|---|---|---|---|
| Extractive (default) | `LLM_PROVIDER=none` or unset | Top cited passage, no generation | Nothing |
| Local open-weight model | `LLM_PROVIDER=openai_compatible` + local URL | Generated, cited answer | A model server on your machine (below) |
| OpenRouter (hosted) | `LLM_PROVIDER=openai_compatible` + OpenRouter URL + key | Generated, cited answer | An OpenRouter key and an account setting (below) |

If the model is slow, down, or does not cite a passage, the API serves the extractive answer and sets `degraded` to `llm_unavailable` or `llm_uncited`.

**Local model (tested).** The model runs as its own process. Qwen2.5-0.5B-Instruct (Apache-2.0, Q4_K_M, about 490 MB) is the tested model. It is too small for reliable answers. Use a 3B to 7B model for real use.

```bash
# Model server, in its own environment
python3 -m venv ~/llm-venv && ~/llm-venv/bin/pip install "llama-cpp-python[server]" huggingface_hub
~/llm-venv/bin/python -c "from huggingface_hub import hf_hub_download as d; d('Qwen/Qwen2.5-0.5B-Instruct-GGUF','qwen2.5-0.5b-instruct-q4_k_m.gguf',local_dir='$HOME/models')"
~/llm-venv/bin/python -m llama_cpp.server --model ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8090 --n_ctx 2048

# API (local clone)
export LLM_PROVIDER=openai_compatible LLM_BASE_URL=http://127.0.0.1:8090/v1 \
       LLM_MODEL=qwen2.5-0.5b LLM_TIMEOUT_S=60
```

For the Docker image, bind the model server to the Docker bridge address (`--host 172.17.0.1`), not to `127.0.0.1`, so the container can reach it without exposing it on every interface. Then set `LLM_BASE_URL=http://host.docker.internal:8090/v1`.

`LLM_TIMEOUT_S=60` is needed on CPU. The design budget is 250 ms, which no CPU-hosted model meets.

**OpenRouter (hosted; the data leaves your network).** OpenRouter exposes open-weight models through an OpenAI-compatible API. Your query text, after PII redaction, is sent to OpenRouter and the model provider it routes to. Check your data policy before you enable it.

```bash
export LLM_PROVIDER=openai_compatible LLM_BASE_URL=https://openrouter.ai/api/v1 \
       LLM_MODEL=meta-llama/llama-3.3-70b-instruct LLM_API_KEY=<your OpenRouter key>
```

Set the key in your environment or secret manager. Do not put it in a file or a command you share. Rotate any key that was pasted into chat or a ticket.

Before a model slug works, the account must allow the model's providers. Open https://openrouter.ai/workspaces/default/guardrails and adjust the data and guardrail settings. As of this writing, several open-weight models (`meta-llama/llama-3.3-70b-instruct`, `qwen/qwen-2.5-72b-instruct`, `mistralai/mistral-small-3.2-24b-instruct`, `google/gemma-3-4b-it`, `openai/gpt-oss-20b`) return 404 with "matching your guardrail restrictions", and `qwen/qwen-2.5-7b-instruct` has been retired. List current models with `curl https://openrouter.ai/api/v1/models`.

Turn any mode off by unsetting `LLM_PROVIDER`, then restart. More detail, including the custom-provider path, is in [deployment.md](deployment.md) section 9.

**Latency:** the neural backend (`RETRIEVAL_BACKEND=full`) takes about 9 s per query on CPU, against a 380 ms loop budget. Queries then return `status: degraded`. Use `lexical` until the reranker is batched or run on GPU. See [gaps.md](gaps.md) Phase 3.

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
curl -s localhost:8000/api/v1/agent/query -H "Authorization: Bearer $CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{"request_id":"3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f","tenant_id":"tenant_acme","user_id":"user_1","query":"What is the returns policy?"}'
```

Configuration (environment variables): `VAULT_DIR` (default `knowledge_vault/`), `ALLOWED_TENANTS` (default `tenant_acme`).

## Workbench

`streamlit run app.py` opens six tabs: architecture and HITL queue, RAG lab with live sliders, MCP and plugin inspector with the real validator, memory and token estimates, red team and circuit breaker, and the KPI scorecard with a live latency run. The workbench runs the pipeline in its own process, so its approval queue and cache are separate from a running API server.

## Known gaps versus design.md

- The lexical reranker and light stemmer are stand-ins. Retrieval quality is not measured yet, so KPI-10 to KPI-13 are unverified.
- By default answers are passages, not generated text. The optional LLM is not yet measured for faithfulness (RAGAS not run), so generated answers are unverified.
- The API runs in one process with in-memory cache, audit, and HITL state. Nothing survives a restart.
- Latency and load KPIs are unmeasured. The 36-KPI scorecard does not exist yet.

## Conventions

- Python 3.11+, FastAPI, Pydantic v2 with `strict=True`.
- Commits and PRs follow the rules in `workflow.md` § C.1.
- A change to any number in `design.md` requires an ADR in `docs/adr/`.
