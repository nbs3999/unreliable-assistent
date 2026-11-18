"""Bounded ReAct state machine (design.md ADR-04, Gate 4).

INIT -> TRIAGE -> REASONING -> TOOL_CALL -> OBSERVATION -> VERIFY -> DONE | HALTED_*
Limits: max_iterations=5, loop budget 380 ms, tool step 120 ms, LLM step 250 ms.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class State(str, Enum):
    INIT = "INIT"
    TRIAGE = "TRIAGE"
    REASONING = "REASONING"
    TOOL_CALL = "TOOL_CALL"
    OBSERVATION = "OBSERVATION"
    VERIFY = "VERIFY"
    DONE = "DONE"
    HALTED_BREAKER = "HALTED_BREAKER"
    HALTED_BUDGET = "HALTED_BUDGET"
    HALTED_TIMEOUT = "HALTED_TIMEOUT"


TERMINAL = {State.DONE, State.HALTED_BREAKER, State.HALTED_BUDGET, State.HALTED_TIMEOUT}

ALLOWED: dict[State, set[State]] = {
    State.INIT: {State.TRIAGE},
    State.TRIAGE: {State.REASONING, State.DONE},
    State.REASONING: {State.TOOL_CALL, State.VERIFY, State.HALTED_BUDGET},
    State.TOOL_CALL: {State.OBSERVATION, State.HALTED_BREAKER, State.HALTED_TIMEOUT},
    State.OBSERVATION: {State.REASONING, State.HALTED_BUDGET},
    State.VERIFY: {State.DONE, State.REASONING},
}


class InvalidTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class LoopBudget:
    max_iterations: int = 5
    loop_budget_ms: float = 380.0
    tool_step_ms: float = 120.0
    llm_step_ms: float = 250.0


class ReActLoop:
    def __init__(self, budget: LoopBudget | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.budget = budget or LoopBudget()
        self._clock = clock
        self._start = clock()
        self.state = State.INIT
        self.iterations = 0
        self.halt_reason: str | None = None
        self.history: list[str] = [State.INIT.value]

    def elapsed_ms(self) -> float:
        return (self._clock() - self._start) * 1000.0

    def advance(self, to: State) -> State:
        if self.state in TERMINAL:
            raise InvalidTransition(f"loop already terminal ({self.state.value})")
        if to not in ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {to.value} is not allowed")
        # Budget is checked on every transition, so a slow step cannot start another one.
        if to not in TERMINAL and self.elapsed_ms() > self.budget.loop_budget_ms:
            return self._halt(State.HALTED_BUDGET, "loop budget exceeded")
        if to is State.REASONING and self.state in (State.OBSERVATION, State.VERIFY):
            self.iterations += 1
            if self.iterations >= self.budget.max_iterations:
                return self._halt(State.HALTED_BUDGET, "max iterations reached")
        self.state = to
        self.history.append(to.value)
        return self.state

    def _halt(self, state: State, reason: str) -> State:
        self.state = state
        self.halt_reason = reason
        self.history.append(state.value)
        return state
