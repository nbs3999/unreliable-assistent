"""Tier 3 human-in-the-loop store. A mutation runs only after an approved decision."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from assistant.contracts import ErrorCode, ToolError


@dataclass
class PendingApproval:
    approval_id: str
    tenant_id: str
    request_id: str
    action: str
    args: dict[str, Any]
    status: str = "PENDING_APPROVAL"  # -> APPROVED | REJECTED
    reviewer: str | None = None


class HitlStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingApproval] = {}

    def request(self, tenant_id: str, request_id: str, action: str, args: dict[str, Any]) -> PendingApproval:
        item = PendingApproval(str(uuid.uuid4()), tenant_id, request_id, action, args)
        self._items[item.approval_id] = item
        return item

    def decide(self, approval_id: str, reviewer: str, approve: bool) -> PendingApproval:
        item = self._items.get(approval_id)
        if item is None:
            raise ToolError(ErrorCode.E_INVALID_REQUEST, "unknown approval_id")
        if item.status != "PENDING_APPROVAL":
            raise ToolError(ErrorCode.E_IDEMPOTENT_REPLAY, f"already {item.status}")
        item.status = "APPROVED" if approve else "REJECTED"
        item.reviewer = reviewer
        return item

    def all(self) -> list[PendingApproval]:
        return list(self._items.values())

    def get(self, approval_id: str, tenant_id: str) -> PendingApproval | None:
        item = self._items.get(approval_id)
        if item is None or item.tenant_id != tenant_id:
            return None  # tenant mismatch is reported as not found, not as a leak
        return item
