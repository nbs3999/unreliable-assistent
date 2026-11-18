"""Idempotent circuit breaker: trips when (tool_name, canonical_args_hash) fails >= max times."""
from __future__ import annotations

from collections import Counter
from typing import Any

from assistant.contracts import ErrorCode, ToolError
from assistant.harness.idempotency import canonical_hash


class CircuitBreaker:
    def __init__(self, max_identical_calls: int = 2) -> None:
        self.max = max_identical_calls
        self._failures: Counter[tuple[str, str]] = Counter()

    def check(self, tool: str, args: Any) -> None:
        if self._failures[(tool, canonical_hash(args))] >= self.max:
            raise ToolError(ErrorCode.E_BREAKER_OPEN,
                            f"'{tool}' with identical arguments failed {self.max} times; "
                            "change the request or contact support")

    def record_failure(self, tool: str, args: Any) -> None:
        self._failures[(tool, canonical_hash(args))] += 1

    def snapshot(self) -> list[dict]:
        return [{"tool": t, "args_hash": h[:16] + "…", "failures": n, "open": n >= self.max}
                for (t, h), n in self._failures.items()]

    def reset(self) -> None:
        self._failures.clear()
