# Implementation plans

Implementation plans for Nao Bridge — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202610071850_existing-code-to-green.md](202610071850_existing-code-to-green.md) | Bring pre-SDD code through lint/type-check/tests, package imports + entry points, fix `stop_expressive_reaction` (delivered by the robot/bridge split) | Done |
| [202610071906_robot-bridge-split.md](202610071906_robot-bridge-split.md) | Robot seam / bridge architecture: `robot.py` seam (`real`/`fake`) + `NaoBridge` in `bridge.py`; servers ported; fast-tier tests | Done |
| [202610081509_config-and-stream-apis.md](202610081509_config-and-stream-apis.md) | `NaoBridgeConfig` + server configs + `--config` CLIs; stream APIs replacing callbacks (touch `Event`, joints `Observable`, mic feed with `audio_input()` subscribers) | Done |
| [202610081629_qi-as-a-platform-dependency.md](202610081629_qi-as-a-platform-dependency.md) | `qi==3.1.6` declared from the fork's wheels on macOS arm64 / Linux x86_64 (CPython 3.12–3.13); other platforms install fake-only | Done |
| [202610081653_mcp-stdout-reserved-for-the-protocol.md](202610081653_mcp-stdout-reserved-for-the-protocol.md) | libqi's native console log no longer corrupts the MCP stdio channel: fd 1 → stderr while serving, the transport on a private dup | Done |
| [202610081700_bounded-connection-attempts.md](202610081700_bounded-connection-attempts.md) | `robot.connect_timeout_s` (5 s): each qi connection attempt is bounded instead of waiting ~76 s on a silent host | Done |
| [202610081713_fake-behaviors-take-time.md](202610081713_fake-behaviors-take-time.md) | Fake behaviors last 5 s by default (stoppable), so running/stopping is observable offline; the fast tier sets them to 0 | Done |
| [202610081816_robot-backends-in-their-own-modules.md](202610081816_robot-backends-in-their-own-modules.md) | `QiNaoRobot` → `RealNaoRobot` in `real_robot.py`, `FakeNaoRobot` in `fake_robot.py`; `robot.py` keeps the Protocol and `build_robot` | Done |
| [202610081830_websocket-server-fixes.md](202610081830_websocket-server-fixes.md) | WebSocket server: a bad message no longer closes the session, a client swap logs no spurious error, every `CommandEnded` carries `data` | Done |
| [202610081835_spec-and-doc-drift.md](202610081835_spec-and-doc-drift.md) | Editorial spec/README gaps closed (MCP tool list, constructor signature, ring wording, testing/import sentences); the unused `raw` alias removed; relative imports in the servers | Done |
| [202610081840_websocket-server-restructure.md](202610081840_websocket-server-restructure.md) | `ClientSession` (protocol over a connection-like object) split from `NaoWebsocketServer` (bridge + listener); command table; typed; `server.host` | Done |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
