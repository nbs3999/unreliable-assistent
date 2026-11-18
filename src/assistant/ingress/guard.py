"""Pre-execution guard. Both plugins are fail-closed: any exception rejects the request."""
from __future__ import annotations

from dataclasses import dataclass, field

from assistant.contracts import ErrorCode, ToolError
from assistant.ingress.injection import find_injection
from assistant.ingress.pii import redact


@dataclass
class GuardResult:
    text: str
    blocked: bool = False
    block_reasons: list[str] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)


def run_pre_execution(text: str) -> GuardResult:
    try:
        redacted, counts = redact(text)
        hits = find_injection(redacted)
    except Exception as exc:  # fail closed (design.md § 1.8)
        raise ToolError(ErrorCode.E_DEGRADED, "pre-execution guard unavailable; request rejected",
                        {"stage": "PRE_EXECUTION"}) from exc
    return GuardResult(text=redacted, blocked=bool(hits),
                       block_reasons=hits, redactions=counts)
