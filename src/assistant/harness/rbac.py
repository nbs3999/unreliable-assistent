"""RBAC tier ceilings per subagent (design.md § 1.2.1 and Gate 7)."""
from __future__ import annotations

from assistant.contracts import ErrorCode, Tier, ToolError

_RANK = {Tier.TIER_1_READ: 1, Tier.TIER_2_COMPUTE: 2, Tier.TIER_3_MUTATE: 3}

SUBAGENT_CEILINGS: dict[str, Tier] = {
    "retrieval": Tier.TIER_1_READ,      # read-only; cannot invoke mutating tools
    "verification": Tier.TIER_1_READ,   # audit append is a write to the log, not business state
    "execution": Tier.TIER_3_MUTATE,    # Tier 3 still needs HITL approval (enforced elsewhere)
}


def check_tier(subagent: str, requested: Tier) -> None:
    ceiling = SUBAGENT_CEILINGS.get(subagent)
    if ceiling is None:
        raise ToolError(ErrorCode.E_RBAC_DENIED, f"unknown subagent '{subagent}'")
    if _RANK[requested] > _RANK[ceiling]:
        raise ToolError(
            ErrorCode.E_RBAC_DENIED,
            f"{subagent} may not call {requested.value} tools",
            {"subagent": subagent, "ceiling": ceiling.value},
        )
