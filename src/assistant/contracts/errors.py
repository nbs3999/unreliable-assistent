"""JSON-RPC error codes from design.md § 1.2.3."""
from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    E_INVALID_REQUEST = -32600
    E_VALIDATION = -32602
    E_TENANT_FORBIDDEN = -32001
    E_TIMEOUT = -32002
    E_BREAKER_OPEN = -32003
    E_HITL_PENDING = -32004
    E_RBAC_DENIED = -32005
    E_IDEMPOTENT_REPLAY = -32006
    E_DEGRADED = -32007


class ToolError(Exception):
    """Raised by the harness and pipeline; carries a design.md error code."""

    def __init__(self, code: ErrorCode, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_jsonrpc(self) -> dict:
        return {"code": int(self.code), "name": self.code.name,
                "message": self.message, "data": self.data}
