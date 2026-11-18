"""FastAPI application. Run: uvicorn assistant.api.app:app --app-dir src"""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from assistant.api.auth import ROLE_REVIEWER, ROLE_USER, KeyStore, require_principal
from assistant.api.pipeline import Deps, handle_query
from assistant.cache import SemanticCacheStore
from assistant.config import load_settings
from assistant.contracts import ErrorCode, QueryRequest, QueryResponse, ToolError
from assistant.governance import AuditLog, HitlStore
from assistant.llm import build_llm
from assistant.rag import CrossEncoderReranker, DenseIndex, KnowledgeBase

_STATUS = {
    ErrorCode.E_TENANT_FORBIDDEN: 403, ErrorCode.E_RBAC_DENIED: 403,
    ErrorCode.E_VALIDATION: 422, ErrorCode.E_INVALID_REQUEST: 400,
    ErrorCode.E_DEGRADED: 503, ErrorCode.E_TIMEOUT: 504,
    ErrorCode.E_BREAKER_OPEN: 409, ErrorCode.E_IDEMPOTENT_REPLAY: 409,
    ErrorCode.E_HITL_PENDING: 202,
}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


def build_deps() -> Deps:
    s = load_settings()
    kb = KnowledgeBase.load(s.vault_dir)
    dense = reranker = None
    if s.retrieval_backend == "full":
        dense = DenseIndex([c.search_text for c in kb.chunks], [c.chunk_id for c in kb.chunks], s.embed_model)
        reranker = CrossEncoderReranker(s.rerank_model)
    return Deps(
        kb=kb,
        cache=SemanticCacheStore(s.cache_ttl_s, s.cache_jitter_s),
        audit=AuditLog(),
        hitl=HitlStore(),
        allowed_tenants=s.allowed_tenants,
        dense=dense,
        reranker=reranker,
        keys=KeyStore.from_file(s.api_keys_file),
        llm=build_llm(s.llm_provider, base_url=s.llm_base_url, model=s.llm_model,
                      api_key=s.llm_api_key, timeout_s=s.llm_timeout_s),
    )


def create_app(deps: Deps | None = None) -> FastAPI:
    app = FastAPI(title="The Unreliable Assistant", version="0.2.0")
    app.state.deps = deps or build_deps()

    @app.exception_handler(ToolError)
    async def _tool_error(_: Request, exc: ToolError) -> JSONResponse:
        headers = {"Retry-After": "5"} if exc.code is ErrorCode.E_DEGRADED else None
        return JSONResponse(status_code=_STATUS.get(exc.code, 500),
                            content={"error": exc.to_jsonrpc()}, headers=headers)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "vault_chunks": len(app.state.deps.kb.chunks)}

    @app.post("/api/v1/agent/query", response_model=QueryResponse)
    async def query(body: QueryRequest, request: Request,
                    authorization: str | None = Header(default=None),
                    x_api_key: str | None = Header(default=None),
                    x_tenant_id: str | None = Header(default=None)) -> QueryResponse:
        principal = require_principal(app.state.deps.keys, authorization, x_api_key, ROLE_USER)
        return handle_query(body, app.state.deps, header_tenant=x_tenant_id, principal=principal)

    @app.get("/api/v1/hitl/pending")
    async def list_pending(authorization: str | None = Header(default=None),
                           x_api_key: str | None = Header(default=None)) -> dict:
        principal = require_principal(app.state.deps.keys, authorization, x_api_key, ROLE_REVIEWER)
        items = [{"approval_id": p.approval_id, "action": p.action, "status": p.status,
                  "request_id": p.request_id}
                 for p in app.state.deps.hitl.all()
                 if p.tenant_id == principal.tenant_id and p.status == "PENDING_APPROVAL"]
        return {"items": items}

    @app.post("/api/v1/hitl/{approval_id}/decision")
    async def decide(approval_id: str, body: DecisionIn,
                     authorization: str | None = Header(default=None),
                     x_api_key: str | None = Header(default=None)) -> dict:
        deps = app.state.deps
        principal = require_principal(deps.keys, authorization, x_api_key, ROLE_REVIEWER)
        item = deps.hitl.get(approval_id, principal.tenant_id)
        if item is None:
            raise ToolError(ErrorCode.E_INVALID_REQUEST, "unknown approval_id")
        decided = deps.hitl.decide(approval_id, reviewer=principal.user_id,
                                   approve=body.decision == "approve")
        deps.audit.append({"event": "hitl_decision", "approval_id": approval_id,
                           "tenant_id": principal.tenant_id, "reviewer": principal.user_id,
                           "decision": decided.status})
        # No execution path exists yet (gaps.md Phase 6): an approval is recorded but nothing runs.
        return {"approval_id": approval_id, "status": decided.status, "executed": False}

    return app


app = create_app()
