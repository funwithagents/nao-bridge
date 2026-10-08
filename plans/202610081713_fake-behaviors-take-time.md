# Fake behaviors take time

**Status:** Done

Implements the edits to `specs/robot.md` (the fake's behavior runs) and `specs/testing.md` (instant fake behaviors in the fast tier), both `Updated`. On the fake, every behavior (dance, body action, app, expressive reaction, raw `run_behavior`) finishes instantly: `FakeNaoRobot.behavior_duration_s` defaults to `0.0`. So nothing is ever seen running, every stop verb returns `False`, a WebSocket `StopDance` is always an `Error`, and the MCP tools return at once where the robot would hold them for the whole behavior.

The fake becomes realistic by default: **5 s per behavior** (`FakeNaoRobot.DEFAULT_BEHAVIOR_DURATION_S`), still stoppable at any moment. The fast tier opts out: an autouse fixture in `tests/conftest.py` sets the class default to `0.0` for every test, and a test marked `fake_behavior_durations` keeps the real default. Tests that need a running behavior keep setting `behavior_duration_s` on the instance, as today.

Not in scope: per-kind durations, and a config field for the duration. Both are noted in the analysis notes if a demo needs them.

## Scope

- `src/nao_bridge/robot.py` — `FakeNaoRobot.DEFAULT_BEHAVIOR_DURATION_S = 5.0`; `__init__` sets `behavior_duration_s` from it.
- `tests/conftest.py` — the autouse fixture, with the `fake_behavior_durations` opt-out.
- `pyproject.toml` — register the `fake_behavior_durations` marker.
- `tests/test_bridge.py` — under the marker: on a fresh fake, a dance is still running after a moment and `stop_dance` ends it (without waiting the 5 s).
- `specs/robot.md`, `specs/testing.md`, `specs/_index.md`.

## Steps

1. Spec edits → `Updated`.
2. The default in `robot.py`.
3. The fixture (`monkeypatch.setattr(FakeNaoRobot, "DEFAULT_BEHAVIOR_DURATION_S", 0.0)` unless the test has the marker), the marker registration, and the new test.
4. Check that the full suite's duration is unchanged (no test silently waits 5 s), and that the MCP / WebSocket subprocess tests don't run a behavior.
5. Specs → `Implemented`, this plan → `Done`.

## Verification

Done 2026-10-08:
- ruff and pyright are clean, and 105 tests pass in ~2.0 s (the new test accounts for the extra 0.2 s); the slowest test takes 0.26 s.
- With the fixture temporarily disabled, the bridge, MCP and WebSocket test files took 16.5 s: the fixture is what keeps the tier fast.
- Over a real WebSocket against the default (fake) server: a `Dance` answered `Success` after 5.0 s, and a `StopDance` sent 1 s into another dance succeeded and ended it at 1.0 s.

The original checklist:

ruff, pyright and pytest all clean, and the suite takes about as long as before (~1.8 s). On the fake from the CLI side: a `Dance` command over WebSocket answers after ~5 s, and a `StopDance` sent meanwhile succeeds.
