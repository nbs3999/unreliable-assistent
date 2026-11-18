import pytest
from assistant.loop import InvalidTransition, LoopBudget, ReActLoop, State


class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def test_happy_path_reaches_done():
    loop = ReActLoop(clock=FakeClock())
    for s in [State.TRIAGE, State.REASONING, State.TOOL_CALL, State.OBSERVATION,
              State.REASONING, State.VERIFY, State.DONE]:
        loop.advance(s)
    assert loop.state is State.DONE


def test_illegal_transition_is_rejected():
    loop = ReActLoop(clock=FakeClock())
    with pytest.raises(InvalidTransition):
        loop.advance(State.TOOL_CALL)


def test_budget_exceeded_halts_before_next_step():
    clock = FakeClock()
    loop = ReActLoop(LoopBudget(loop_budget_ms=380), clock=clock)
    loop.advance(State.TRIAGE)
    clock.t = 0.5  # 500 ms elapsed
    assert loop.advance(State.REASONING) is State.HALTED_BUDGET
    with pytest.raises(InvalidTransition):
        loop.advance(State.TOOL_CALL)


def test_max_iterations_halts_loop():
    loop = ReActLoop(clock=FakeClock())
    loop.advance(State.TRIAGE)
    loop.advance(State.REASONING)
    for _ in range(4):
        loop.advance(State.TOOL_CALL)
        loop.advance(State.OBSERVATION)
        loop.advance(State.REASONING)
    loop.advance(State.TOOL_CALL)
    loop.advance(State.OBSERVATION)
    assert loop.advance(State.REASONING) is State.HALTED_BUDGET
    assert loop.halt_reason == "max iterations reached"
