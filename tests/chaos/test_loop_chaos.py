"""KPI-16: infinite loop escape rate must be 100%. Adversarial loop attempts."""
import itertools
import pytest
from assistant.loop import InvalidTransition, ReActLoop, State


class Tick:
    def __init__(self, step_ms): self.t, self.step = 0.0, step_ms / 1000.0
    def __call__(self):
        self.t += self.step
        return self.t


@pytest.mark.parametrize("step_ms", [1, 50, 120, 400])
def test_every_path_terminates(step_ms):
    loop = ReActLoop(clock=Tick(step_ms))
    loop.advance(State.TRIAGE)
    steps = 0
    try:
        while loop.state not in {State.DONE, State.HALTED_BUDGET, State.HALTED_BREAKER, State.HALTED_TIMEOUT}:
            steps += 1
            assert steps < 100, "loop did not terminate"
            loop.advance(State.REASONING)
            loop.advance(State.TOOL_CALL)
            loop.advance(State.OBSERVATION)
    except InvalidTransition:
        pass
    assert loop.state in {State.DONE, State.HALTED_BUDGET, State.HALTED_BREAKER, State.HALTED_TIMEOUT}


def test_no_transition_out_of_terminal_state():
    loop = ReActLoop(clock=Tick(1))
    loop.advance(State.TRIAGE)
    loop.advance(State.DONE)
    for target in State:
        with pytest.raises(InvalidTransition):
            loop.advance(target)
