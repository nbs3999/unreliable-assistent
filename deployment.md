# deployment.md — Deployment Guide

Written for: the operator deploying the API and the engineers issuing API keys to clients.
Companion to `gaps.md` (open gaps) and `design.md` (target architecture).

---

## 1. What is deployed

| Component | Deployed? | Notes |
|---|---|---|
| FastAPI API (`assistant.api.app`) | **Yes** | The only service. Runs in one container under uvicorn. |
| Streamlit workbench (`app.py`) | **No** | Developer tool. It runs its own copy of the pipeline, so it is not connected to the API's data. Do not expose it. |
| MCP servers (`mcp_servers/`) | No | Not built yet (gaps.md Phase 2). |
| Redis, Postgres | No | Not wired in. Cache, audit and approvals are in-process (gaps.md § 1.3). |
| LLM service | **Optional** | Off by default (extractive answers). Enable by pointing the API at an OpenAI-compatible model server (section 9). The model runs as its own service, not inside the API image. |
| OTel / Prometheus / Grafana | No | Not built (gaps.md Phase 7). |

Endpoints:
- `GET /health` — no auth. Returns status and vault chunk count.
- `POST /api/v1/agent/query` — requires a **user** API key.
- `GET /api/v1/hitl/pending` — requires a **reviewer** API key.
- `POST /api/v1/hitl/{approval_id}/decision` — requires a **reviewer** API key.

---

## 2. Topology constraint: run exactly one replica

Cache, HITL approvals, the audit chain and the idempotency store all live in process memory. Two replicas would have separate caches, separate approval queues and separate audit chains, and an approval made on one replica would not be visible on the other.

**Rule:** run one API container (`--workers 1`, one replica) until Postgres and Redis are integrated. The Dockerfile already sets `--workers 1`.

A restart clears the cache and any pending approvals, and resets the audit chain. Do not treat restarts as safe until persistence lands.

---

## 3. API keys and other credentials

### 3.1 Keys you need now

| Credential | Required? | Who holds it | How to get it |
|---|---|---|---|
| **Service API keys** (one per client user or service) | **Yes**, to call the API | Each client | Issued by the operator with `scripts/make_api_key.py` (section 4) |
| **Reviewer API keys** | Yes, for HITL approvals | Each approver | Same script, with `--roles reviewer` |
| LLM provider key (`LLM_API_KEY`) | Only for hosted providers | Operator | Not needed for a local open-weight model. For a hosted OpenAI-compatible API, set `LLM_API_KEY` from a secret manager. Never commit it. |
| `HF_TOKEN` (Hugging Face) | Optional | Operator | Embedding and reranker models (`BAAI/bge-*`) are public and download without a token. A token raises rate limits and speeds up first start. |
| Redis / Postgres credentials | Not yet | — | Required once those stores are integrated (gaps.md § 1.3). |
| OTel collector address | Not yet | — | Required with observability (gaps.md Phase 7). |

### 3.2 What the API key does

- It identifies one caller and binds that caller to **one tenant and one user**.
- A request whose body `tenant_id` or `user_id` differs from the key's binding is rejected with **403**. A caller cannot act as another user by changing the body.
- Keys are stored **only as SHA-256 digests** in the keys file. The raw key is shown once, at issue time, and cannot be recovered. Lose it and issue a new one.
- Keys are sent as `Authorization: Bearer <key>` (or `X-API-Key: <key>`).

### 3.3 Authentication failures

| Situation | Response |
|---|---|
| No key, or unknown key | 401 |
| User key on a reviewer route, or reviewer key on the query route | 403 |
| Body `tenant_id` or `user_id` does not match the key | 403 |
| Tenant not in `ALLOWED_TENANTS` | 403 |

---

## 4. Issuing, rotating and revoking keys

Keys live in a JSON file that the service reads at startup. Keep this file out of git (it is in `.gitignore`) and restrict its permissions.

### Issue a client key

```bash
python scripts/make_api_key.py --keys-file /etc/assistant/api_keys.json \
    --tenant tenant_acme --user user_1 --roles user
```

The script prints the raw key once. Give it to the client over a secure channel.

### Issue a reviewer key

```bash
python scripts/make_api_key.py --keys-file /etc/assistant/api_keys.json \
    --tenant tenant_acme --user user_reviewer_1 --roles reviewer
```

### Rotate or revoke

Keys are read at **startup only**. After editing the file, restart the service.

- **Revoke:** delete the entry for that key from the file, then restart.
- **Rotate:** issue a new key for the same user, give it to the client, then delete the old entry and restart.

There is no hot reload and no per-key expiry yet (gaps.md § 1.1).

---

## 5. Configuration (environment variables)

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `API_KEYS_FILE` | unset | **Yes** | Path to the keys JSON. With no file, every authenticated route returns 401. |
| `ALLOWED_TENANTS` | `tenant_acme` | Yes | Comma-separated tenant IDs the service accepts. |
| `RETRIEVAL_BACKEND` | `full` | No | `full` needs the `models` extra and downloads models on first start. `lexical` uses BM25 only and needs no models. |
| `EMBED_MODEL` | `BAAI/bge-large-en-v1.5` | No | Used when `RETRIEVAL_BACKEND=full`. |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | No | Used when `RETRIEVAL_BACKEND=full`. |
| `VAULT_DIR` | `<project>/knowledge_vault` | No | Knowledge base location. The image sets this path by default. |
| `HF_TOKEN` | unset | No | Hugging Face token (optional, see 3.1). |
| `HF_HOME` | `/models/hf` (image) | No | Where model weights are cached. Mount a volume here so restarts do not re-download. |
| `LLM_PROVIDER` | `none` | No | `none` = extractive answers. `openai_compatible` = any OpenAI-style chat server. `package.module:ClassName` = your own provider. |
| `LLM_BASE_URL` | unset | With a provider | Base URL including `/v1`, e.g. `http://model-host:8090/v1`. |
| `LLM_MODEL` | unset | With `openai_compatible` | Model name the server expects. |
| `LLM_API_KEY` | unset | Hosted providers | Bearer token, sent only to `LLM_BASE_URL`. |
| `LLM_TIMEOUT_S` | `0.25` | No | Per-call timeout. The design budget is 250 ms, which no CPU-hosted model meets. Raise it for CPU hosts; a timeout falls back to extractive answers. |

The cache TTL (300 s ± 45 s) is set in code (`config/settings.py`), not by environment variable.

---

## 6. Build and run

**Published image:** none yet. Build locally, or share a saved image file:

```bash
docker save unreliable-assistant:0.2.0 | gzip > unreliable-assistant-0.2.0.tar.gz   # share this file
docker load -i unreliable-assistant-0.2.0.tar.gz                                     # on the other machine
```

The image is about 2.2 GB, mostly CPU torch and the sentence-transformers stack. Building needs about 5 GB free disk.

### Requirements

- Docker 24 or later, or a Python 3.11+ environment.
- For `RETRIEVAL_BACKEND=full`: about 2 GB disk for model weights and enough RAM to load them. Start-up takes minutes on CPU while models load.

### Build the image

```bash
docker build -t unreliable-assistant:0.2.0 .
```

The image contains the API, the knowledge vault and `mcp_config.json`. It does not contain keys, `.env` files, tests, or the Streamlit app (see `.dockerignore`).

### Run (container)

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -e API_KEYS_FILE=/run/secrets/api_keys.json \
  -e ALLOWED_TENANTS=tenant_acme \
  -e RETRIEVAL_BACKEND=lexical \
  -v "$PWD/api_keys.json:/run/secrets/api_keys.json:ro" \
  unreliable-assistant:0.2.0
```

- Use `RETRIEVAL_BACKEND=full` in production and add a volume for model weights: `-v assistant-models:/models`.
- Bind to `127.0.0.1` locally, or put the service behind a TLS-terminating gateway (NGINX or Envoy, per `design.md` § 1.3). Do not publish port 8000 directly to the internet.

### Run (from source, without Docker)

```bash
pip install -e ".[dev,models]"          # drop ",models" for lexical-only
export API_KEYS_FILE=$PWD/api_keys.json
export ALLOWED_TENANTS=tenant_acme
uvicorn assistant.api.app:app --app-dir src --port 8000 --workers 1
```

### Smoke test

```bash
curl -s localhost:8000/health

curl -s localhost:8000/api/v1/agent/query \
  -H "Authorization: Bearer $CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{"request_id":"3f1c2a9e-7b4d-4c1a-9e2f-1a2b3c4d5e6f","tenant_id":"tenant_acme","user_id":"user_1","query":"What is the returns policy?"}'
```

Expected: `"status":"ok"`, a `sources` list, and `"route":"HYBRID_RAG"`.

Check that an out-of-scope question abstains:

```bash
... -d '{"...","query":"What is the current stock price of the company?"}'
```

Expected: `"status":"abstained"` with empty `sources`.

### Approval flow

```bash
# Reviewer lists pending approvals
curl -s localhost:8000/api/v1/hitl/pending -H "Authorization: Bearer $REVIEWER_KEY"

# Reviewer approves or rejects
curl -s -X POST localhost:8000/api/v1/hitl/<approval_id>/decision \
  -H "Authorization: Bearer $REVIEWER_KEY" -H 'Content-Type: application/json' \
  -d '{"decision":"approve"}'
```

An approval is recorded in the audit log and returns `"executed": false`. **No action runs yet**: the execution path is not built (gaps.md Phase 6).

---

## 7. Verifying a deployment

Before you trust a build:

1. `pytest -q` passes in a clean install (CI runs this).
2. The retrieval eval on the target backend: `python eval/retrieval_eval.py --backend full`. Check that `abstention_accuracy_negatives` is no longer 0.0. Compare with `eval/reports/retrieval-full.json`, which is the pre-fix report.
3. The smoke test above.

---

## 8. Known limits in this release

These are open items in `gaps.md`. Do not describe this release as production-ready until they are closed.

- In-memory state only: cache, approvals, audit and idempotency are lost on restart (gaps.md § 1.3).
- Single replica only (section 2).
- LLM answers are **off by default**. When enabled, a citation check is the only faithfulness control. A 0.5B-parameter model misread a policy passage in testing (see section 9.4). Run RAGAS before enabling it for users.
- No observability stack, no rate limiting, no load testing, no red-team run beyond the 15-prompt smoke set.
- Key revocation needs a restart; there is no per-key expiry or audit of key use beyond the request audit.
- Tier 3 approvals do not trigger any action yet.
- **`RETRIEVAL_BACKEND=full` does not meet the latency budget on CPU.** In the container, retrieval took about 9.4 s per query, against a 380 ms loop budget. Every in-scope query then returns `status: degraded` with `loop_budget_exceeded`. Use `lexical` until the reranker is batched or run on GPU hardware. Measure on the target machine before choosing `full`.

---

## 9. Optional: local open-weight LLM

The API can answer with a generated, cited answer from an open-weight model. The API does not load the model. It calls the model's HTTP server, so you can swap models or turn the LLM off without changing code.

### 9.1 Start a model server

The tested setup uses llama.cpp's OpenAI-compatible server. Install it in its own environment, not in the API's:

```bash
python -m venv ~/llm-venv && ~/llm-venv/bin/pip install "llama-cpp-python[server]" huggingface_hub

# Download a GGUF model (Apache-2.0 example)
~/llm-venv/bin/python -c "from huggingface_hub import hf_hub_download as d; \
d('Qwen/Qwen2.5-0.5B-Instruct-GGUF','qwen2.5-0.5b-instruct-q4_k_m.gguf',local_dir='$HOME/models')"

# Serve it on an internal port. Bind to 127.0.0.1 for a local clone.
# For the Docker image, bind to the Docker bridge address instead (usually 172.17.0.1, see `ip -4 addr show docker0`).
~/llm-venv/bin/python -m llama_cpp.server --model $HOME/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  --host 127.0.0.1 --port 8090 --n_ctx 2048
```

Tested model: **Qwen2.5-0.5B-Instruct** (`Qwen/Qwen2.5-0.5B-Instruct-GGUF`, file `qwen2.5-0.5b-instruct-q4_k_m.gguf`, Apache-2.0). Too small for reliable policy answers; use a 3B to 7B model for real use.

### 9.2 Point the API at it

```bash
export LLM_PROVIDER=openai_compatible
export LLM_BASE_URL=http://127.0.0.1:8090/v1
export LLM_MODEL=qwen2.5-0.5b
export LLM_TIMEOUT_S=60          # CPU hosts need a much longer timeout than the 250 ms design budget
```

Any OpenAI-compatible server works the same way: Ollama (`http://host:11434/v1`), vLLM (`http://host:8000/v1`), or a hosted endpoint with `LLM_API_KEY`. Set `LLM_MODEL` to the name that server expects.

### 9.2a Reaching the model from the Docker container

Run the container with a host alias and point `LLM_BASE_URL` at it:

```bash
docker run --rm -p 127.0.0.1:8000:8000 --add-host=host.docker.internal:host-gateway \
  -e API_KEYS_FILE=/run/secrets/api_keys.json -e RETRIEVAL_BACKEND=lexical \
  -e LLM_PROVIDER=openai_compatible -e LLM_BASE_URL=http://host.docker.internal:8090/v1 \
  -e LLM_MODEL=qwen2.5-0.5b -e LLM_TIMEOUT_S=60 \
  -v "$PWD/api_keys.json:/run/secrets/api_keys.json:ro" unreliable-assistant:0.2.0
```

With the model bound to `127.0.0.1`, the container cannot reach it (the request falls back to extractive, `llm_unavailable`). Bind the model server to the Docker bridge address (`--host 172.17.0.1`), which is reachable from containers but not from other machines. Tested: this path returns `mode: generated`.

### 9.2b OpenRouter (hosted)

```bash
export LLM_PROVIDER=openai_compatible
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_MODEL=<a model slug your account can use>
export LLM_API_KEY=<key from your secret manager>   # never in a file or a shared command
```

- Your query text, after PII redaction, goes to OpenRouter and the provider it routes to. Check your data policy first.
- Model slugs fail with HTTP 404 until the account allows their providers. Adjust the data and guardrail settings at https://openrouter.ai/workspaces/default/guardrails. At the time of writing, `meta-llama/llama-3.3-70b-instruct`, `qwen/qwen-2.5-72b-instruct`, `mistralai/mistral-small-3.2-24b-instruct`, `google/gemma-3-4b-it` and `openai/gpt-oss-20b` were all blocked by guardrail restrictions, and `qwen/qwen-2.5-7b-instruct` was retired. List current slugs with `curl https://openrouter.ai/api/v1/models`.
- Tested: with the account blocked, the API falls back to extractive with `llm_unavailable`, and the key does not appear in container logs. A working model call through OpenRouter has not yet been verified.
- Rotate the key if it was pasted anywhere outside your secret manager.

### 9.3 Plug in and plug out

- **Turn off:** unset `LLM_PROVIDER` (or set `none`) and restart. Answers return to extractive.
- **Swap model:** change `LLM_MODEL` and the model server's `--model`. No code change.
- **Custom provider:** write a class with `name` and `generate(request)` that returns text or raises `LLMError`, then set `LLM_PROVIDER=yourpkg.module:YourClass`.

### 9.4 What the answer looks like, and what it does not guarantee

- A generated answer is served only if it cites a valid passage (`[1]`, `[2]`, ...). Otherwise the API serves the extractive answer and sets `degraded: llm_uncited`.
- If the model is down, slow, or errors, the API serves the extractive answer and sets `degraded: llm_unavailable`.
- If the model replies `INSUFFICIENT_CONTEXT`, the response is `abstained`.
- **A citation is not proof of faithfulness.** In testing, Qwen2.5-0.5B cited the right passage but misstated the refund time. Measure faithfulness (RAGAS, gaps.md Phase 3) before serving generated answers to users, and use a larger model (1.5B or more; 3B to 7B is better for policy text).
- Latency: the test host (4 CPU cores) answered a short prompt in about one second, and a grounded answer took about 3.7 s end to end. That is above the 250 ms design budget, so the LLM step will time out there unless you raise `LLM_TIMEOUT_S`. A GPU host is needed for the design budget.
