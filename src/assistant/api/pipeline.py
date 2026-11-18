"""Request pipeline: ingress -> cache -> triage -> loop -> response (workflow.md § B.1).

Pass a list as `trace` to receive the step-by-step record (used by the workbench).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from assistant.agents import classify
from assistant.cache import SemanticCacheStore, build_key
from assistant.contracts import (
    ErrorCode, HybridRetrieveInput, HybridRetrieveOutput, QueryRequest, QueryResponse,
    Route, Tier, ToolError,
)
from assistant.governance import AuditLog, HitlStore
from assistant.harness import ToolExecutionHarness, repair_codes_in_text
from assistant.ingress import run_pre_execution
from assistant.loop import ReActLoop, State
from assistant.rag import CrossEncoderReranker, DenseIndex, KnowledgeBase, Reranker, retrieve  # noqa: F401


@dataclass
class Deps:
    kb: KnowledgeBase
    cache: SemanticCacheStore
    audit: AuditLog
    hitl: HitlStore
    allowed_tenants: tuple[str, ...]
    dense: DenseIndex | None = None
    reranker: Reranker | None = None
    harness: ToolExecutionHarness = field(default_factory=lambda: ToolExecutionHarness("retrieval"))


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 3)


def _audit(deps: Deps, req: QueryRequest, route: str, status: str) -> None:
    # Stores a digest of the query, never the text (zero raw PII persistence).
    deps.audit.append({
        "request_id": req.request_id, "tenant_id": req.tenant_id, "user_id": req.user_id,
        "route": route, "status": status,
        "query_sha256": hashlib.sha256(req.query.encode("utf-8")).hexdigest(),
    })


def _emit(trace: list | None, step: str, **detail) -> None:
    if trace is not None:
        trace.append({"step": step, **detail})


def handle_query(req: QueryRequest, deps: Deps, header_tenant: str | None = None,
                 trace: list | None = None) -> QueryResponse:
    timings: dict[str, float] = {}
    total0 = time.perf_counter()

    if req.tenant_id not in deps.allowed_tenants:
        raise ToolError(ErrorCode.E_TENANT_FORBIDDEN, "tenant is not provisioned")
    if header_tenant is not None and header_tenant != req.tenant_id:
        raise ToolError(ErrorCode.E_TENANT_FORBIDDEN, "X-Tenant-ID does not match body tenant_id")

    # Ingress: PII redaction and injection screen (fail closed on exception)
    t0 = time.perf_counter()
    guard = run_pre_execution(req.query)
    timings["hook_pre"] = _ms(t0)
    _emit(trace, "hook.pre", ms=timings["hook_pre"], redactions=guard.redactions,
          blocked=guard.blocked, reasons=guard.block_reasons, text_after_guard=guard.text)
    if guard.blocked:
        _audit(deps, req, "REJECT_OOS", "refused")
        return QueryResponse(request_id=req.request_id, route=Route.REJECT_OOS, status="refused",
                             answer="This request was refused by the safety policy.", timings_ms=timings)

    # Cache: tenant-scoped key with a tenant re-check on read
    key = build_key(req.tenant_id, req.user_id, guard.text)
    t0 = time.perf_counter()
    cached = deps.cache.get(key, req.tenant_id)
    timings["cache_lookup"] = _ms(t0)
    _emit(trace, "cache.lookup", ms=timings["cache_lookup"], hit=cached is not None)
    if cached is not None:
        response = cached.model_copy(update={"request_id": req.request_id,
                                             "timings_ms": {**timings, "total": _ms(total0)}})
        _audit(deps, req, response.route.value, "cache_hit")
        return response

    # Triage: deterministic routing
    t0 = time.perf_counter()
    triage = classify(guard.text)
    timings["triage"] = _ms(t0)
    _emit(trace, "triage.classify", ms=timings["triage"], route=triage.route.value,
          risk_tier=triage.risk_tier.value, confidence=triage.confidence)

    loop = ReActLoop()
    loop.advance(State.TRIAGE)

    if triage.route is Route.REJECT_OOS:
        loop.advance(State.DONE)
        resp = QueryResponse(request_id=req.request_id, route=triage.route, status="refused",
                             answer="That is outside what I can help with. Ask about company policies, SOPs, or catalog items.")

    elif triage.route is Route.DIRECT_ANSWER:
        loop.advance(State.DONE)
        resp = QueryResponse(request_id=req.request_id, route=triage.route, status="ok",
                             answer="Hello. Ask me about company policies, SOPs, or catalog items.")

    elif triage.route is Route.TRANSACTION_EXEC:
        # Tier 3: never executes here. A PENDING_APPROVAL record is written; a reviewer decides.
        loop.advance(State.DONE)
        pending = deps.hitl.request(req.tenant_id, req.request_id, "submit_request",
                                    {"query_sha256": hashlib.sha256(guard.text.encode()).hexdigest()})
        _emit(trace, "hitl.request", approval_id=pending.approval_id, status=pending.status)
        resp = QueryResponse(request_id=req.request_id, route=triage.route, status="pending_approval",
                             answer=f"This action needs human approval before it can run. Reference: {pending.approval_id}")

    else:  # HYBRID_RAG
        loop.advance(State.REASONING)
        loop.advance(State.TOOL_CALL)
        t0 = time.perf_counter()
        try:
            retrieval_input = {"request_id": req.request_id, "tenant_id": req.tenant_id,
                               "query": repair_codes_in_text(guard.text)}
            call = deps.harness.call(
                tool="hybrid_retrieve", tier=Tier.TIER_1_READ, model=HybridRetrieveInput,
                payload=retrieval_input,
                handler=lambda inp: retrieve(deps.kb, inp.query, dense=deps.dense,
                                             reranker=deps.reranker, top_k=inp.top_k,
                                             rerank_k=inp.rerank_k, threshold=inp.threshold),
            )
        except ToolError as exc:
            if exc.code is not ErrorCode.E_DEGRADED:
                raise
            loop.advance(State.HALTED_TIMEOUT)
            timings["retrieval"] = _ms(t0)
            timings["total"] = _ms(total0)
            _emit(trace, "tool.hybrid_retrieve", ms=timings["retrieval"], error=exc.code.name)
            _emit(trace, "loop.history", states=loop.history)
            resp = QueryResponse(request_id=req.request_id, route=triage.route, status="degraded",
                                 answer="Retrieval is temporarily unavailable. Please retry shortly.",
                                 degraded=["retrieval_unavailable"], timings_ms=timings)
            _audit(deps, req, triage.route.value, "degraded")
            return resp
        timings["retrieval"] = _ms(t0)
        result = call.value
        validated = HybridRetrieveOutput.model_validate(
            {"abstain": result.abstain, "chunks": result.chunks, "stage_ms": result.stage_ms})
        _emit(trace, "tool.hybrid_retrieve", ms=timings["retrieval"], repairs=call.repairs,
              stage_ms=result.stage_ms, degraded=result.degraded, abstain=validated.abstain)

        loop.advance(State.OBSERVATION)
        loop.advance(State.REASONING)
        loop.advance(State.VERIFY)
        loop.advance(State.DONE)

        degraded = list(result.degraded)
        if validated.abstain:
            resp = QueryResponse(request_id=req.request_id, route=triage.route, status="abstained",
                                 answer="I could not find a supported answer in the approved documents.",
                                 degraded=degraded)
        else:
            top = validated.chunks[0]
            # Extractive mode: the answer is the top passage, quoted and cited. No free generation.
            resp = QueryResponse(
                request_id=req.request_id, route=triage.route, status="ok",
                answer=f"From the approved documents: {top.text[:400]}",
                sources=[{"chunk_id": c.chunk_id, "chunk_hash": c.chunk_hash} for c in validated.chunks],
                degraded=degraded,
            )

    timings["total"] = _ms(total0)
    resp.timings_ms.update(timings)
    _emit(trace, "loop.history", states=loop.history)
    if resp.status in ("ok", "abstained", "refused"):
        deps.cache.set(key, req.tenant_id, resp)
    _audit(deps, req, triage.route.value, resp.status)
    return resp
