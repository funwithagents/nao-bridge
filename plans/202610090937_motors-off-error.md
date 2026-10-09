# Motors-off error for verbs that move the body

**Status:** Done

Implements the settled behavior in `specs/bridge.md` ("Action verb contract", "Errors") and `specs/robot.md` ("The consumed slice", "`FakeNaoRobot`"). A verb that moves the body checks with the robot that its motors are on and raises `MotorsOffError` when they aren't, so a caller (an agent through MCP above all) learns to call `wake_up()` first. It leaves out waking the robot automatically: turning motors on stays an explicit act.

## Scope

- `src/nao_bridge/robot.py`: `is_awake() -> bool` on the `NaoRobot` Protocol.
- `src/nao_bridge/real_robot.py`: `is_awake()` over `ALMotion.robotIsWakeUp`.
- `src/nao_bridge/fake_robot.py`: an `awake` flag (starts `False`), set by `wake_up()`, cleared by `rest()`, read by `is_awake()` (not recorded).
- `src/nao_bridge/errors.py`, `src/nao_bridge/__init__.py`: `MotorsOffError(BridgeError)`, exported.
- `src/nao_bridge/bridge.py`: `_require_awake(verb)`, called by `stand_up`, `sit_down`, `set_breathing_enabled(True, …)`, `run_behavior` and the catalog verbs (after the catalog lookup, before tracking). The catalog verbs run their behavior through an internal `_run_behavior`, so the error names the verb the caller used.
- `tests/test_bridge.py`, `tests/test_fake_robot.py`, `tests/test_real_robot.py`, `tests/test_nao_mcp_server.py`: tests that move the body wake the fake first; new tests for the error, which verbs check and which don't, the MCP result string, and the real backend's call.
- `README.md`: the error in the API section.

## Steps

1. Protocol method, both backends.
2. Error class and export.
3. The bridge check and the internal `_run_behavior` split.
4. Tests and README; specs back to `Implemented`.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean.
