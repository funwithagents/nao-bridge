# Nao Bridge

Nao Bridge connects AI agents to Aldebaran's Nao robot (and, in principle, any robot running Naoqi). Its core idea is a single high-level, async Python API — `NaoBridge` — that hides the Naoqi `qi` session and services behind intent-level actions (speak, change posture, dance, react expressively, run an installed app) and streams the robot's touch, joint and audio data back out. Two thin adapters expose that one API to different clients without duplicating logic: an MCP server for LLM agents (Claude Desktop, Tiny Agents) and a JSON WebSocket server for custom apps. The bridge sits on a robot seam with two backends, a real robot over `qi` or an offline fake, so the whole stack runs and is tested without hardware or the `qi` wheel.

## Specs

<!-- One row per concept spec. Keep the Status column in sync with each spec's `**Status:**` line. -->

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions | Implemented |
| [testing.md](testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, skip-without-credentials live tier | Implemented |
| [robot.md](robot.md) | Connection seam: the `NaoRobot` Protocol, `QiNaoRobot` over `qi` (lazy import, no silent fallback), `FakeNaoRobot` (records commands, fixed package list, simulated behavior runs and sensor events), `build_robot(backend)` | Implemented |
| [bridge.md](bridge.md) | `NaoBridge`: `start()`/`stop()`/`async with` lifecycle, `bool` action verbs, the behavior catalog classifier, running-item tracking and stop semantics, touch/joints/audio streams, `bridge.robot` escape hatch | Implemented |
| [nao-mcp-server.md](nao-mcp-server.md) | `NaoMcpServer`: the MCP tool surface over `NaoBridge`, one-loop serving, and the `nao-mcp-server` CLI | Implemented |
| [nao-websocket-server.md](nao-websocket-server.md) | `NaoWebsocketServer`: single-client JSON WebSocket protocol, commands and streamed events | Implemented |

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
