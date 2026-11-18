"""In-process cache with tenant re-check on read and jittered TTL (300 s +/- 45 s).

Production backs this with Redis Cluster. The tenant check on every hit is a second
line of defense: a key collision must not return another tenant's entry.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Entry:
    tenant_id: str
    value: Any
    expires_at: float


class SemanticCacheStore:
    def __init__(self, base_ttl_s: float = 300.0, jitter_s: float = 45.0,
                 clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None) -> None:
        self.base_ttl_s = base_ttl_s
        self.jitter_s = jitter_s
        self._clock = clock
        self._rng = rng or random.Random()
        self._data: dict[str, _Entry] = {}
        self.isolation_violations = 0

    def get(self, key: str, tenant_id: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            del self._data[key]
            return None
        if entry.tenant_id != tenant_id:
            self.isolation_violations += 1  # must stay 0 (KPI-28)
            return None
        return entry.value

    def set(self, key: str, tenant_id: str, value: Any) -> None:
        ttl = self.base_ttl_s + self._rng.uniform(-self.jitter_s, self.jitter_s)
        self._data[key] = _Entry(tenant_id, value, self._clock() + ttl)

    def snapshot(self) -> list[dict]:
        """Keys (truncated), tenants, and remaining TTL only. Values are never exposed."""
        now = self._clock()
        return [{"key": k[:16] + "…", "tenant_id": e.tenant_id,
                 "ttl_left_s": round(max(0.0, e.expires_at - now), 1)}
                for k, e in self._data.items()]
