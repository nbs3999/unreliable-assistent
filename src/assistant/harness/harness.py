"""ToolExecutionHarness: every tool call passes through here (design.md § 1.2.4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from assistant.contracts import ErrorCode, Tier, ToolError
from assistant.harness.circuit_breaker import CircuitBreaker
from assistant.harness.idempotency import IdempotencyStore
from assistant.harness.rbac import check_tier
from assistant.harness.repair import repair_args


@dataclass
class ToolCallResult:
    value: Any
    repairs: list[dict] = field(default_factory=list)
    replayed: bool = False


class ToolExecutionHarness:
    def __init__(self, subagent: str, idempotency: IdempotencyStore | None = None,
                 breaker: CircuitBreaker | None = None) -> None:
        self.subagent = subagent
        self.idempotency = idempotency or IdempotencyStore()
        self.breaker = breaker or CircuitBreaker()

    def call(self, *, tool: str, tier: Tier, model: type[BaseModel], payload: dict,
             handler: Callable[[BaseModel], Any]) -> ToolCallResult:
        # 3. RBAC tier check (done first so denied calls never reach validation/handlers)
        check_tier(self.subagent, tier)

        # 1+2. Strict validation, then one deterministic repair pass, then validate again
        validated, repairs = self._validate_with_repair(model, payload)

        args = validated.model_dump(mode="json")
        tenant = args.get("tenant_id", "")

        # 4. Idempotency for mutating calls
        if tier is Tier.TIER_3_MUTATE:
            key = args.get("idempotency_key")
            if not key:
                raise ToolError(ErrorCode.E_VALIDATION, "idempotency_key is required for mutations")
            found, stored = self.idempotency.lookup(tenant, key, args)
            if found:
                return ToolCallResult(value=stored, repairs=repairs, replayed=True)

        # Circuit breaker
        self.breaker.check(tool, args)
        try:
            result = handler(validated)
        except ToolError:
            self.breaker.record_failure(tool, args)
            raise
        if tier is Tier.TIER_3_MUTATE:
            self.idempotency.store(tenant, args["idempotency_key"], args, result)
        return ToolCallResult(value=result, repairs=repairs)

    @staticmethod
    def _validate_with_repair(model: type[BaseModel], payload: dict):
        try:
            return model.model_validate(payload, strict=True), []
        except ValidationError:
            pass
        repaired, repairs = repair_args(payload)
        if not repairs:
            raise ToolError(ErrorCode.E_VALIDATION, "payload failed schema validation")
        try:
            return model.model_validate(repaired, strict=True), repairs
        except ValidationError as exc:
            raise ToolError(ErrorCode.E_VALIDATION, "payload invalid even after auto-repair",
                            {"errors": exc.error_count()}) from exc
