# ADR-04 — Bounded ReAct loops
Status: Accepted (design.md § 1.7).
Decision: state machine INIT→TRIAGE→REASONING→TOOL_CALL→OBSERVATION→VERIFY→DONE|HALTED_*. max_iterations 5, loop budget 380 ms (not the Blueprint's 450 ms), tool step 120 ms, LLM step 250 ms. Worst case 442 ms end to end.
Implemented in `src/assistant/loop/state_machine.py`; chaos tests in `tests/chaos/`.
