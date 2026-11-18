import uuid
import pytest
from pydantic import BaseModel, Field
from assistant.contracts import ErrorCode, Tier, ToolError
from assistant.harness import ToolExecutionHarness, check_tier
from assistant.harness.circuit_breaker import CircuitBreaker
from assistant.harness.idempotency import IdempotencyStore


class SkuInput(BaseModel):
    model_config = {"strict": True, "extra": "forbid"}
    tenant_id: str
    sku: str = Field(pattern=r"^SKU-\d{3}$")
    idempotency_key: str = ""


def test_rbac_blocks_retrieval_from_mutating_tools():
    with pytest.raises(ToolError) as exc:
        check_tier("retrieval", Tier.TIER_3_MUTATE)
    assert exc.value.code is ErrorCode.E_RBAC_DENIED


def test_rbac_allows_execution_up_to_tier3():
    check_tier("execution", Tier.TIER_3_MUTATE)


def test_harness_repairs_then_calls_handler():
    h = ToolExecutionHarness("retrieval")
    out = h.call(tool="lookup", tier=Tier.TIER_1_READ, model=SkuInput,
                 payload={"tenant_id": "tenant_acme", "sku": "SKU99"},
                 handler=lambda m: m.sku)
    assert out.value == "SKU-099"
    assert out.repairs[0]["repaired"] == "SKU-099"


def test_harness_rejects_unrepairable_payload():
    h = ToolExecutionHarness("retrieval")
    with pytest.raises(ToolError) as exc:
        h.call(tool="lookup", tier=Tier.TIER_1_READ, model=SkuInput,
               payload={"tenant_id": "tenant_acme", "sku": "widget"}, handler=lambda m: m)
    assert exc.value.code is ErrorCode.E_VALIDATION


def test_mutation_replay_returns_stored_result_without_rerunning():
    h = ToolExecutionHarness("execution")
    calls = {"n": 0}

    def handler(m):
        calls["n"] += 1
        return {"done": True}

    key = str(uuid.uuid4())
    payload = {"tenant_id": "tenant_acme", "sku": "SKU-001", "idempotency_key": key}
    first = h.call(tool="submit", tier=Tier.TIER_3_MUTATE, model=SkuInput, payload=payload, handler=handler)
    again = h.call(tool="submit", tier=Tier.TIER_3_MUTATE, model=SkuInput, payload=payload, handler=handler)
    assert calls["n"] == 1
    assert again.replayed and again.value == first.value


def test_same_idempotency_key_different_args_is_rejected():
    store = IdempotencyStore()
    key = str(uuid.uuid4())
    store.store("tenant_acme", key, {"a": 1}, "r")
    with pytest.raises(ToolError) as exc:
        store.lookup("tenant_acme", key, {"a": 2})
    assert exc.value.code is ErrorCode.E_IDEMPOTENT_REPLAY


def test_circuit_breaker_trips_after_two_identical_failures():
    h = ToolExecutionHarness("retrieval", breaker=CircuitBreaker(max_identical_calls=2))

    def boom(m):
        raise ToolError(ErrorCode.E_DEGRADED, "down")

    payload = {"tenant_id": "tenant_acme", "sku": "SKU-001"}
    for _ in range(2):
        with pytest.raises(ToolError):
            h.call(tool="lookup", tier=Tier.TIER_1_READ, model=SkuInput, payload=payload, handler=boom)
    with pytest.raises(ToolError) as exc:
        h.call(tool="lookup", tier=Tier.TIER_1_READ, model=SkuInput, payload=payload, handler=boom)
    assert exc.value.code is ErrorCode.E_BREAKER_OPEN
