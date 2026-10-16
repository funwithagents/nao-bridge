# Posture observable

**Status:** Done

Implements `bridge.posture` as specified in [bridge.md](../specs/bridge.md) ("Posture"), the seam calls in [robot.md](../specs/robot.md) ("The consumed slice", "`FakeNaoqiRobot`"), the no-switch rule in [config.md](../specs/config.md) ("Streams") and the live tests in [testing.md](../specs/testing.md). It deliberately leaves out the servers: no WebSocket `Posture` message and no MCP tool yet.

## Scope

- `src/naoqi_bridge/robot.py` — `PostureKey`, `POSTURE_KEYS`, `PostureCallback`; `get_posture`, `subscribe_posture`, `unsubscribe_posture` in the Protocol
- `src/naoqi_bridge/real_robot.py` — the three calls over `ALRobotPosture` and `ALMemory`
- `src/naoqi_bridge/fake_robot.py` — `POSTURE_FAMILIES`, the three calls, events on a posture change, the `posture_event` helper
- `src/naoqi_bridge/bridge.py` — `PostureState`, `bridge.posture`, the read and subscription at `start()`, `moving_to` around `stand_up` / `sit_down` / `rest`, the read after a move, `None` at `stop()`
- `src/naoqi_bridge/__init__.py` — export `PostureState`
- `tests/test_bridge.py`, `tests/test_fake_robot.py`, `tests/test_real_robot.py` — functional tests
- `tests-e2e/test_live_streams.py`, `tests-e2e/test_live_motion.py` — the live tests
- `AGENTS.md`, `specs/_overview.md`, `specs/_index.md` — the map and summaries

## Steps

1. Seam: the Protocol methods and types; `RealNaoqiRobot` reads `getPosture` / `getPostureFamily` and subscribes the two `ALMemory` keys like touch, `cb(key, value)`.
2. Fake: `get_posture()` from `posture` and `POSTURE_FAMILIES`; a subscribed callback receives `PostureChanged` (then `PostureFamilyChanged` if the family changed) whenever `posture` changes; `posture_event(key, value)` calls it with anything.
3. Bridge: `_posture: Observable[PostureState | None]`; in `_bring_up`, read then subscribe (one warning on failure, the observable stays `None`); `_forward_posture` marshals onto the loop; `_publish_posture` sets only on a change.
4. Bridge moves: `_span` and `_act` already hand out the robot call's future (`started`); a posture move records its target and future, publishes `moving_to`, and on the future's end clears it (if still the newest) and starts a read task. `stand_up` / `sit_down` / `rest` await that read on their normal path.
5. `stop()`: unsubscribe with touch, cancel a pending read, publish `None`.
6. Tests, the live tests, the docs.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`; the live tier's posture tests on a 2.1 and a 2.8 sim, and on the robot when it is reachable. Then this plan `Done`, and bridge.md, robot.md and testing.md back to `Implemented`.
