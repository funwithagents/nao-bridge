# naoqi-bridge

naoqi-bridge connects AI agents to Aldebaran's Nao robot (and, in principle, any robot running Naoqi). Its core idea is a single high-level, async Python API — `NaoqiBridge` — that hides the Naoqi `qi` session and services behind intent-level actions (speak, change posture, dance, react expressively, run an installed app) and streams the robot's touch, joint and audio data back out. Two thin adapters expose that one API to different clients without duplicating logic: an MCP server for LLM agents (Claude Desktop, Tiny Agents) and a JSON WebSocket server for custom apps. The bridge sits on a robot seam with two backends, a real robot over `qi` or an offline fake, so the whole stack runs and is tested without hardware or the `qi` wheel.

[_overview.md](_overview.md) is the map of the whole project: goals, scope, architecture, how a call flows, the cross-cutting rules, where each part stands, and the open questions collected from the specs. It is reference material without a status; the concept specs below are the authority on their details.

## Specs

<!-- One row per concept spec. Keep the Status column in sync with each spec's `**Status:**` line. -->

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, `qi>=3.1.8` from the libqi package index (macOS arm64, Linux x86_64, Windows x64; fake-only elsewhere), layout conventions | Updated |
| [testing.md](testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, skip-without-credentials live tier; fake behaviors, speech and postures made instant; live tier on a sim (default) or a robot, in three opt-in levels (safe, motion, interactive) with measured cancel latencies | Updated |
| [ci.md](ci.md) | Continuous integration: `check` (lint, format, types) on `ubuntu-24.04` and `fast-tier` on Linux, macOS and Windows runners, side by side, every pull request and push to `main`; `e2e-sim`: the live tier on a headless sim, per NAOqi version | Updated |
| [config.md](config.md) | `NaoqiBridgeConfig` (backend — `fake` by default, `real` or `sim` —, robot connection, streams, the `sim` block) with the `from_dict` / `from_json` / `from_json_file` loaders and `ConfigError`; streams as switches for the bridge's stream APIs; `{"bridge", "server"}` server configs; `--config`-only CLIs; example files | Updated |
| [robot.md](robot.md) | Connection seam: the `AnyNaoqiRobot` Protocol and `build_robot(config)` in `robot.py`; `NaoqiRobot` over `qi` (`naoqi_robot.py` lazy import, no silent fallback, one cancellable connect attempt), `FakeNaoqiRobot` (`fake_robot.py`; records commands, fixed package list, simulated behavior runs, speech and posture moves that take time and can be stopped, joints of the posture it's in, sensor events, paced audio push); `stop_posture` | Updated |
| [bridge.md](bridge.md) | `NaoqiBridge`: built from a config; `start()`/`stop()`/`async with` lifecycle, action verbs that raise why they failed (`BridgeError` subclasses, `ValueError`), the behavior catalog classifier, running-item tracking and stop semantics, stream APIs (`on_touch`, `joints`, `mic` / `audio_input()`), `bridge.robot` escape hatch; every verb cancellable (a cancelled spanning verb stops its effect on the robot before re-raising) | Updated |
| [sim.md](sim.md) | The `sim` backend: a naoqi-sim the bridge starts and owns or borrows (`sim.spawn`: `auto`, `never`, `always`), connected through `NaoqiRobot`; the `[sim]` extra; what a sim offers the bridge | Stable |
| [events.md](events.md) | `Event[T]`: synchronous pub/sub, subscription-order dispatch, subscriber isolation — `bridge.on_touch` | Implemented |
| [observable.md](observable.md) | `Observable[T]`: `value`, latest-wins `changes()`, `wait_for`, `set` vs `update` — `bridge.joints` | Implemented |
| [microphone.md](microphone.md) | Mic feed: one subscription to Naoqi's pushed audio, a 200-chunk ring, any number of `audio_input()` subscribers each with its own cursor, lap warnings, `preroll_s`, `bridge.mic.latest()` | Implemented |
| [naoqi-mcp-server.md](naoqi-mcp-server.md) | `NaoqiMcpServer`: the MCP tool surface over `NaoqiBridge`, one-loop serving, and the `naoqi-mcp-server` CLI | Implemented |
| [naoqi-websocket-server.md](naoqi-websocket-server.md) | `NaoqiWebsocketServer`: single-client JSON WebSocket protocol, commands and streamed events | Implemented |

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
