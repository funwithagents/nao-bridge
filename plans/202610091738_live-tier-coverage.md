# Live tier coverage

**Status:** Done

Implements `specs/testing.md` ("Live tier: levels of risk"). Adds live tests that cover the bridge's verbs, its streams, the cancellation contract ([bridge.md](../specs/bridge.md) "Cancellation") and both servers against a real Nao, at three opt-in levels: safe, motion and interactive. Cancel latencies are measured and printed. What it leaves out: running these tests on a robot. That needs a Nao and someone watching it, so it's tracked in [analysis/202610091738_not-yet-tested-on-a-robot.md](../analysis/202610091738_not-yet-tested-on-a-robot.md) and not done here. No library code changes, apart from a stale MCP docstring.

## Scope

- `tests-e2e/support.py` — `require_flag`, `live_config`, `live_session`, catalog pickers, `behavior_running` (asks `ALBehaviorManager`), `measure_cancel` + the `MEASUREMENTS` record.
- `tests-e2e/conftest.py` — prints the recorded measurements in the terminal summary.
- `tests-e2e/test_live_verbs.py` — safe: speech and TTS language, `stop_say`, eyes, basic awareness, unknown ids, the motors check.
- `tests-e2e/test_live_streams.py` — safe: joints, audio (measures the real chunk size); interactive: touch.
- `tests-e2e/test_live_cancellation.py` — safe: cancelled `say`, cancelled `start()` against an address that doesn't answer; motion: cancelled dance (late, and at once), body action, `stand_up`, and a timeout around a reaction.
- `tests-e2e/test_live_motion.py` — motion: motors and `MotorsOffError`, postures, breathing, a body action, a reaction, a dance stopped by `stop_dance`.
- `tests-e2e/test_live_servers.py` — safe: the MCP server over stdio through the `mcp` client; motion: the WebSocket server with all streams, over a loopback socket.
- `tests-e2e/test_live_robot.py` — unchanged.
- `src/nao_bridge/nao_mcp_server.py` — `_cancel_runs` docstring: cancelling a run now stops its behavior.
- Spec frontmatter `tests:` — the new modules under the specs they exercise (`bridge.md`, `microphone.md`, both server specs).
- `specs/_overview.md` — the live tier line and the testing section.
- `analysis/202610091738_not-yet-tested-on-a-robot.md` — the reminder of what no robot has confirmed yet.

## Steps

1. **Support.** In `support.py`:
   - `require_flag(name)` skips unless the variable is `1` / `true` / `yes`.
   - `live_config(**streams)` builds a `real` config from `require_env("NAO_IP")`, `NAO_PORT` and `connect_tries=2`.
   - `live_session(config, *, motion=False)` is an async context manager. It calls `require_flag("NAO_ALLOW_MOTION")` when `motion` is set, runs the bridge, and calls `wake_up` on entry when moving. On exit it always sets the eyes white, and calls `rest` when moving, logging any failure, so the robot is left as it was found.
   - Pickers: `first_dance` / `first_body_action`, which skip on an empty catalog.
   - `behavior_running(bridge, name)` asks `ALBehaviorManager.isBehaviorRunning` through `RealNaoRobot._service`, with a pyright ignore, because the test wants robot-side truth.
   - `measure_cancel(label, task)` cancels, asserts `CancelledError`, records the latency in `MEASUREMENTS` and returns the seconds.
   - `pytest.importorskip("qi")` in each module.
2. **Summary.** In `conftest.py`, `pytest_terminal_summary` prints `MEASUREMENTS` as a small table when there are any.
3. **Safe verbs, streams and the MCP smoke test.** Assert behavior that holds on any stock Nao: a `say` takes real time; a `stop_say` ends a long one early; every documented eye color is accepted; awareness starts and stops; `dance("no-such-dance")` names the known ids; when the motors are off, `stand_up` raises `MotorsOffError`. For streams: joints have matching names and angles within ±π, and `ts` moves forward; 1 s of audio is about 16000 samples, and the chunk size seen is recorded. For MCP: `stdio_client` on `python -m nao_bridge.nao_mcp_server --config <real config>`, then `initialize`, `list_tools`, `get_dance_list` (JSON) and `say` (no "Nao failed").
4. **Cancellation.** Every motion test stands up first, and each cancel test checks five things:
   - the cancel came back within 2 s;
   - the robot no longer runs the behavior (`behavior_running`);
   - the bridge's tracking is empty;
   - no "did not confirm" / "stopping it failed" warning was logged (`caplog`);
   - the next verb works.
   The "at once" case cancels as soon as the dance is tracked, which exercises the stop re-send. `start()` against `10.255.255.1` (`connect_tries=1`, `connect_timeout_s=2`) needs `qi` but no robot. It doesn't require `NAO_IP`, but it skips without `qi`.
5. **Motion.**
   - Motors and postures: `wake_up` → `is_awake`; `stand_up`, `sit_down`, `stand_up`; breathing on, then off.
   - Behaviors: a body action and `expressive_reaction("Happy")` run to their end. A dance started as a task is stopped by `stop_dance` after 2 s and ends normally.
   - At rest: `rest` → not awake, and `stand_up` raises `MotorsOffError`.
   - WebSocket: `NaoWebsocketServer` on `127.0.0.1:0` with all streams. Check `NaoState` (`fakeRobot: false`), that `Joints` and `Audio` messages arrive, and that `Say` and `ChangeEyesColor` end in `Success`.
6. **Docs and statuses.** Update the spec frontmatter, the overview and the analysis doc. Then set `testing.md` → `Implemented`, this plan → `Done`.

## Verification

- `uv run ruff check .`, `uv run ruff format .`, `uv run pyright` (covers `tests-e2e/`) and `uv run pytest` (the fast tier, unchanged).
- `uv run pytest tests-e2e` with no `NAO_IP` collects every module and skips everything, except the cancelled-`start()` test, which needs only `qi` and runs here.
- `NAO_IP=127.0.0.1 NAO_PORT=1 uv run pytest tests-e2e` fails fast with a connection error, which proves the tests really reach for the robot. Not part of the gate.
- **Not done in this plan:** a run against a real Nao. See the analysis doc.
