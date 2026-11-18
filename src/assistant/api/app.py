"""FastAPI application. Run: uvicorn assistant.api.app:app --app-dir src"""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from assistant.api.pipeline import Deps, handle_query
from assistant.cache import SemanticCacheStore
from assistant.config import load_settings
from assistant.contracts import ErrorCode, QueryRequest, QueryResponse, ToolError
from assistant.governance import AuditLog, HitlStore
from assistant.rag import CrossEncoderReranker, DenseIndex, KnowledgeBase

_STATUS = {
    ErrorCode.E_TENANT_FORBIDDEN: 403, ErrorCode.E_RBAC_DENIED: 403,
    ErrorCode.E_VALIDATION: 422, ErrorCode.E_INVALID_REQUEST: 400,
    ErrorCode.E_DEGRADED: 503, ErrorCode.E_TIMEOUT: 504,
    ErrorCode.E_BREAKER_OPEN: 409, ErrorCode.E_IDEMPOTENT_REPLAY: 409,
    ErrorCode.E_HITL_PENDING: 202,
}


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
    async def query(body: QueryRequest, x_tenant_id: str | None = Header(default=None)) -> QueryResponse:
        return handle_query(body, app.state.deps, header_tenant=x_tenant_id)

    return app


app = create_app()
