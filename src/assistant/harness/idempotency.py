"""Idempotency for mutating calls (design.md § 1.2.4 step 4)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from assistant.contracts import ErrorCode, ToolError


def canonical_hash(obj: Any) -> str:
    """SHA-256 over canonical JSON (sorted keys, no whitespace)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class IdempotencyStore:
    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], tuple[str, Any]] = {}

    def lookup(self, tenant_id: str, key: str, args: Any) -> tuple[bool, Any]:
        """Returns (found, stored_result). Raises on same key with different args."""
        entry = self._seen.get((tenant_id, key))
        if entry is None:
            return False, None
        args_hash, result = entry
        if args_hash != canonical_hash(args):
            raise ToolError(ErrorCode.E_IDEMPOTENT_REPLAY,
                            "idempotency_key reused with different arguments")
        return True, result

    def store(self, tenant_id: str, key: str, args: Any, result: Any) -> None:
        self._seen[(tenant_id, key)] = (canonical_hash(args), result)
