# Implementation plans

Implementation plans for naoqi-bridge — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202610071850_existing-code-to-green.md](202610071850_existing-code-to-green.md) | Bring pre-SDD code through lint/type-check/tests, package imports + entry points, fix `stop_expressive_reaction` (delivered by the robot/bridge split) | Done |
| [202610071906_robot-bridge-split.md](202610071906_robot-bridge-split.md) | Robot seam / bridge architecture: `robot.py` seam (`real`/`fake`) + `NaoqiBridge` in `bridge.py`; servers ported; fast-tier tests | Done |
| [202610081509_config-and-stream-apis.md](202610081509_config-and-stream-apis.md) | `NaoqiBridgeConfig` + server configs + `--config` CLIs; stream APIs replacing callbacks (touch `Event`, joints `Observable`, mic feed with `audio_input()` subscribers) | Done |
| [202610081629_qi-as-a-platform-dependency.md](202610081629_qi-as-a-platform-dependency.md) | `qi==3.1.6` declared from the fork's wheels on macOS arm64 / Linux x86_64 (CPython 3.12–3.13); other platforms install fake-only | Done |
| [202610081653_mcp-stdout-reserved-for-the-protocol.md](202610081653_mcp-stdout-reserved-for-the-protocol.md) | libqi's native console log no longer corrupts the MCP stdio channel: fd 1 → stderr while serving, the transport on a private dup | Done |
| [202610081700_bounded-connection-attempts.md](202610081700_bounded-connection-attempts.md) | `robot.connect_timeout_s` (5 s): each qi connection attempt is bounded instead of waiting ~76 s on a silent host | Done |
| [202610081713_fake-behaviors-take-time.md](202610081713_fake-behaviors-take-time.md) | Fake behaviors last 5 s by default (stoppable), so running/stopping is observable offline; the fast tier sets them to 0 | Done |
| [202610081816_robot-backends-in-their-own-modules.md](202610081816_robot-backends-in-their-own-modules.md) | `QiNaoRobot` → `RealNaoRobot` in `real_robot.py`, `FakeNaoRobot` in `fake_robot.py`; `robot.py` keeps the Protocol and `build_robot` | Done |
| [202610081830_websocket-server-fixes.md](202610081830_websocket-server-fixes.md) | WebSocket server: a bad message no longer closes the session, a client swap logs no spurious error, every `CommandEnded` carries `data` | Done |
| [202610081835_spec-and-doc-drift.md](202610081835_spec-and-doc-drift.md) | Editorial spec/README gaps closed (MCP tool list, constructor signature, ring wording, testing/import sentences); the unused `raw` alias removed; relative imports in the servers | Done |
| [202610081840_websocket-server-restructure.md](202610081840_websocket-server-restructure.md) | `ClientSession` (protocol over a connection-like object) split from `NaoqiWebsocketServer` (bridge + listener); command table; typed; `server.host` | Done |
| [202610081845_broader-ruff-rules.md](202610081845_broader-ruff-rules.md) | Ruff's defaults extended with pycodestyle, perf and annotations (ANN on `src/` only), and the fixes they flag | Done |
| [202610081850_config-defaults-and-errors.md](202610081850_config-defaults-and-errors.md) | Config defaults declared once on the dataclass; `ConfigError.key` instead of message-prefix key paths | Done |
| [202610081855_bridge-mcp-and-robot-cleanups.md](202610081855_bridge-mcp-and-robot-cleanups.md) | One running-items tracker and read-only views in the bridge, tolerant package parsing, `TouchPart`; MCP `_status` helper; real backend audio guard and `close()` cleanup | Done |
| [202610090919_verbs-raise-why-they-failed.md](202610090919_verbs-raise-why-they-failed.md) | `NaoqiBridge` verbs raise (`ValueError` naming the known ids, `NotRunningError`, `NotPlayingError`, `CommandFailedError` chained to Naoqi's error) instead of returning `bool`; the MCP result string and `CommandEnded.message` carry the reason | Done |
| [202610090937_motors-off-error.md](202610090937_motors-off-error.md) | Verbs that move the body (postures, breathing on, behaviors, dances, reactions, body actions, apps) ask the robot `is_awake()` and raise `MotorsOffError` ("call wake_up() first") when the motors are off | Done |
| [202610090943_mcp-tools-start-behaviors.md](202610090943_mcp-tools-start-behaviors.md) | MCP `dance` / `expressive_reaction` / `body_action` / `run_app` run their verb in a server task and return once it's playing (or with why it couldn't start), as the WebSocket server does; `stop_dance` / `stop_expressive_reaction` / `stop_body_action` / `get_running` tools | Done |
| [202610091004_websocket-bind-fallback-and-protocol-version.md](202610091004_websocket-bind-fallback-and-protocol-version.md) | WebSocket server: an empty `host` falls back to `127.0.0.1` with no route out, a failed bind stops the bridge and returns `False`; `NaoState.protocolVersion` (`1`, bumped on incompatible changes only) | Done |
| [202610091016_ci-on-github-runners.md](202610091016_ci-on-github-runners.md) | `.github/workflows/ci.yml`: `check` and `fast-tier` side by side on GitHub's Linux runners for every pull request and push to `main`; the project's first Linux run | Done |
| [202610091714_cancellable-verbs.md](202610091714_cancellable-verbs.md) | Every verb cancellable: a cancelled `say` / posture / behavior / catalog verb sends its stop (re-sent if Naoqi hadn't started yet, owned past a second cancel) and waits for the robot call to end before re-raising; tracking honest until then; `stop_posture` on the seam; timed, stoppable fake speech and postures; cancel-safe `start()` / `stop()` | Done |
| [202610091738_live-tier-coverage.md](202610091738_live-tier-coverage.md) | Live tier in three opt-in levels (safe `NAO_IP`, motion `NAO_ALLOW_MOTION`, interactive `NAO_INTERACTIVE`): verbs, streams, cancellation with measured latencies, both servers against a real Nao; not yet run on a robot | Done |
| [202610091900_fake-joints-follow-its-posture.md](202610091900_fake-joints-follow-its-posture.md) | The fake reports all 26 `Body` joints at the angles of its posture (`Crouch` at rest, `Stand`, `Sit`), following `rest()` and `go_to_posture`; angles measured on a simulated Nao | Done |
| [202610121745_rename-to-naoqi-bridge.md](202610121745_rename-to-naoqi-bridge.md) | Rename to naoqi-bridge: package, `naoqi-mcp-server`/`naoqi-websocket-server` and their modules and specs, `NaoqiBridge*` and server classes, specs and docs; robot names (`NaoRobot`, `NAO_IP`…) kept | Done |
| [202610131500_libqi-index-and-windows.md](202610131500_libqi-index-and-windows.md) | `qi>=3.1.8,<4` from the libqi package index, Windows x64 joins the real backend (others stay fake-only); one connect attempt, `connect_tries` removed, a cancelled `start()` gives up the connection in flight; fast tier on Linux, macOS and Windows; two races Windows exposed fixed (catalog stops confirm the stop, a session closed while opening) | Done |
| [202610131752_nao-names-to-naoqi.md](202610131752_nao-names-to-naoqi.md) | Robot names to Naoqi: `NaoqiRobot` (in `naoqi_robot.py`, was `RealNaoRobot`), `FakeNaoqiRobot`, the `AnyNaoqiRobot` Protocol, `NaoqiBehavior`; the live tier's `NAOQI_E2E_*` variables; the WebSocket protocol's `NaoqiState`, `protocolVersion` 2 | Done |
| [202610131840_sim-backend.md](202610131840_sim-backend.md) | The `sim` backend: a naoqi-sim the bridge starts and owns or borrows (`sim.spawn`), the `[sim]` extra; the live tier on a sim by default (`NAOQI_E2E_TARGET`, `NAOQI_E2E_SIM_VERSION`, `NAOQI_E2E_SIM_VIEWER`), one sim per run; the `e2e-sim` CI job on 2.1 and 2.8 | In progress |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
