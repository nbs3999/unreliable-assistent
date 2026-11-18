"""SHA-256 hash-chained audit log: hash_n = SHA256(prev_hash || canonical(payload))."""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

GENESIS = "0" * 64


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @staticmethod
    def _digest(prev_hash: str, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256((prev_hash + blob).encode("utf-8")).hexdigest()

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else GENESIS
            entry = {"seq": len(self._entries) + 1, "prev_hash": prev, "payload": payload,
                     "hash": self._digest(prev, payload)}
            self._entries.append(entry)
            return entry

    def verify(self) -> bool:
        prev = GENESIS
        for entry in self._entries:
            if entry["prev_hash"] != prev or entry["hash"] != self._digest(prev, entry["payload"]):
                return False
            prev = entry["hash"]
        return True

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
