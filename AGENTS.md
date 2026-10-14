# Agent instructions

Read [specs/_overview.md](specs/_overview.md) for the big picture (goals, architecture, cross-cutting rules, status). Then use [specs/_index.md](specs/_index.md) for an overview of the specs and their status before making design decisions or writing code — it lists each spec and whether it's still open ("Draft"/"Not started"), design-validated ("Stable"), or built ("Implemented"). For what's been (or is being) built, see [plans/_index.md](plans/_index.md), which lists each implementation plan and its status ("Todo"/"In progress"/"Done").

## Project map

Where things live. This is a coarse, module-level map — for the full file inventory use `git ls-files`; for design detail follow the spec links.

### Top-level layout

| Path | What's there |
|---|---|
| `src/naoqi_bridge/` | The library itself — one module per core concept (see below) |
| `specs/` | Pre-implementation design docs, one per concept, each with a `**Status:**` — indexed by [specs/_index.md](specs/_index.md) |
| `plans/` | Implementation plans turning settled specs into buildable steps — indexed by [plans/_index.md](plans/_index.md) |
| `tests/` | Fast, deterministic, no-network tests; mirrors the `src/naoqi_bridge/` module structure |
| `tests-e2e/` | Opt-in live tests that call real external services (not collected by default `pytest`) |
| `.github/workflows/` | The CI workflow: lint, format, types and the fast tier on every pull request and push to `main` — [ci.md](specs/ci.md) |
| `examples/configs/` | Ready-to-use server config files (fake and real, MCP and WebSocket), kept in sync with [config.md](specs/config.md) |

### `src/naoqi_bridge/` modules

<!-- One row per concept module. Keep this in sync with the code (a test enforces it). -->

| Module | Role | Spec |
|---|---|---|
| [`src/naoqi_bridge/__init__.py`](src/naoqi_bridge/__init__.py) | Front door: re-exports what a caller needs — `NaoqiBridge`, the config classes, the stream values (`TouchEvent`, `JointsState`, `MicChunk`), `Event` / `Observable`, the errors | [bridge.md](specs/bridge.md) |
| [`src/naoqi_bridge/config.py`](src/naoqi_bridge/config.py) | `NaoqiBridgeConfig` (backend, robot, streams, sim), the `from_dict` / `from_json` / `from_json_file` loaders, `ConfigError`, field readers reused by server configs | [config.md](specs/config.md) |
| [`src/naoqi_bridge/errors.py`](src/naoqi_bridge/errors.py) | `BridgeError`, shared by the bridge's modules | [bridge.md](specs/bridge.md) |
| [`src/naoqi_bridge/events.py`](src/naoqi_bridge/events.py) | `Event[T]`: synchronous pub/sub primitive (`bridge.on_touch`) | [events.md](specs/events.md) |
| [`src/naoqi_bridge/observable.py`](src/naoqi_bridge/observable.py) | `Observable[T]`: readable, subscribable state (`bridge.joints`) | [observable.md](specs/observable.md) |
| [`src/naoqi_bridge/microphone.py`](src/naoqi_bridge/microphone.py) | `MicFeed` / `MicChunk`: the one subscription to Naoqi's pushed audio, a ring, any number of `audio_input()` subscribers | [microphone.md](specs/microphone.md) |
| [`src/naoqi_bridge/robot.py`](src/naoqi_bridge/robot.py) | Connection seam: the `NaoqiRobot` Protocol, the types/constants both backends share, `RobotConnectionError`, `build_robot(config)` | [robot.md](specs/robot.md) |
| [`src/naoqi_bridge/real_robot.py`](src/naoqi_bridge/real_robot.py) | `RealNaoqiRobot`: the `real` backend, over a `qi` session (lazy import) | [robot.md](specs/robot.md) |
| [`src/naoqi_bridge/sim.py`](src/naoqi_bridge/sim.py) | The `sim` backend's lease: `acquire_sim` starts a naoqi-sim and owns it, or borrows the one running (`sim.spawn`); the one module that starts naoqi-sim (lazy import, `[sim]` extra) | [sim.md](specs/sim.md) |
| [`src/naoqi_bridge/sim_robot.py`](src/naoqi_bridge/sim_robot.py) | `SimNaoqiRobot`: the `sim` backend's robot — `RealNaoqiRobot` at naoqi-sim's address, sitting through Crouch on NAOqi 2.8 | [robot.md](specs/robot.md), [sim.md](specs/sim.md) |
| [`src/naoqi_bridge/fake_robot.py`](src/naoqi_bridge/fake_robot.py) | `FakeNaoqiRobot`: the `fake` backend — records commands, fixed package list, simulated behavior runs and sensor events | [robot.md](specs/robot.md) |
| [`src/naoqi_bridge/bridge.py`](src/naoqi_bridge/bridge.py) | `NaoqiBridge`: built from a `NaoqiBridgeConfig`; `start()`/`stop()` lifecycle, intent-level verbs, behavior catalog, stream APIs (`on_touch`, `joints`, `mic` / `audio_input()`) over the robot seam | [bridge.md](specs/bridge.md) |
| [`src/naoqi_bridge/naoqi_mcp_server.py`](src/naoqi_bridge/naoqi_mcp_server.py) | `NaoqiMcpServer` + `NaoqiMcpServerConfig`: exposes `NaoqiBridge` actions as MCP tools for LLM agents (`--config`) | [naoqi-mcp-server.md](specs/naoqi-mcp-server.md) |
| [`src/naoqi_bridge/naoqi_websocket_server.py`](src/naoqi_bridge/naoqi_websocket_server.py) | `NaoqiWebsocketServer` (bridge + listener, one client at a time) + `ClientSession` (the JSON protocol over one connection: commands in, touch/joints/audio/log events out) + `NaoqiWebsocketServerConfig` (`--config`) | [naoqi-websocket-server.md](specs/naoqi-websocket-server.md) |

**Keep this map current:** when you add, rename, or remove a top-level `src/naoqi_bridge/` module or a root directory, update the map in the same change — same discipline as keeping spec/plan statuses honest (below). A test (`tests/test_project_map.py`) enforces that every `src/naoqi_bridge/*.py` module appears here and vice-versa — and that the spec frontmatter (see below) stays honest too.

## Keeping statuses current

Specs and plans both carry a status, and you are responsible for keeping it honest as work progresses — update it in the same change that does the work, not as an afterthought:

- **Spec status** (`**Status:**` line near the top of each spec, and the Status column in [specs/_index.md](specs/_index.md)) tracks *design maturity* and *whether the code reflects the spec*, as a lifecycle: `Not started` → `Draft` (open questions remain) → `Stable` (design settled, reviewed and validated — open questions are deferrals only — but **not necessarily implemented yet**) → `Implemented` (a `Done` plan has built it and the code matches the spec). Keep the `**Status:**` line and the index row in sync.
  - **`Stable` is the design-review gate, not an implementation claim.** Promote `Draft` → `Stable` once the core design is settled and its remaining open questions are genuine deferrals (not load-bearing unknowns) — this is where the design is validated *before* code is written. No implementation is required to be `Stable`.
  - **`Implemented` means code matches.** Promote `Stable` → `Implemented` only once a plan implementing it is `Done` (lint, type check, tests all pass — see Verification). This is the one transition that asserts design and code are in sync.
  - **When you edit an `Implemented` spec in a way that requires new code, set its status to `Updated` in the same change.** `Updated` means the design is settled but the existing implementation now lags it — a stronger warning than `Stable`, because there is stale code to fix, not just code to write. Then write a new implementation plan for the gap (see below) and, once that plan is `Done`, flip the spec back to `Implemented`. This `Implemented → Updated → Implemented` loop keeps a spec's status an honest signal of whether the code actually matches it — never leave a re-designed spec sitting at `Implemented`.
  - A purely editorial edit to a `Stable` or `Implemented` spec (typos, clarifications, reordering — nothing that changes what the code should do) keeps its status; it does **not** need `Updated`.
- **Plan status** (`**Status:**` line near the top of each plan, and the Status column in [plans/_index.md](plans/_index.md)) tracks *implementation progress*: `Todo` → `In progress` → `Done`. Mark a plan `Done` only once it's implemented and verified (lint, type check, tests all pass — see Verification). Keep the `**Status:**` line and the index row in sync.
- Whenever you add a spec or plan, add its row to the relevant `_index.md`; whenever you change a status, change it in both the file and the index.

## Spec frontmatter

Every spec opens with a YAML frontmatter block naming the code and tests it governs:

```
---
code:
  - src/naoqi_bridge/<module>.py
tests:
  - tests/test_<module>.py
---
```

This is the **spec → code/tests** mapping — the inverse of the module → spec column in the Project map above. Its job is to give the **spec-drift checks** an explicit, version-controlled scope: the exact files to diff a spec against, so a checker never has to guess which code implements a given spec. `code:` names the implementation the spec specifies; `tests:` names the tests that pin its behavior (may be empty/absent).

The mapping is **many-to-many**: a file can be governed by several specs, so the same path legitimately appears in more than one spec's frontmatter.

**Keep it current** (same discipline as statuses): when you move, rename, or delete a file a spec governs — or add a new `src/naoqi_bridge/` module — update the affected spec's `code:`/`tests:` in the same change. `tests/test_project_map.py` enforces three invariants: every listed path exists, every spec declares a non-empty `code:` list, and every concept module in `src/naoqi_bridge/` is named by at least one spec (`__init__.py` is exempt as package glue).

## Testing

- Write functional tests: exercise what a feature/function actually does (inputs → outputs, state changes, side effects), not just that it runs or matches its signature.
- Avoid trivial/tautological tests — e.g. asserting a constant, asserting an object is not `None`, asserting a mock was called. If a test would pass for a broken implementation, it's not worth writing.
- Prefer driving the public API the way a real caller would over asserting on internals.

### Live/e2e tests

Some tests call real external services over the network. They live in `tests-e2e/`, a directory separate from `tests/`, so the default `uv run pytest` never runs them — no network access or credentials are needed for the normal dev loop. Run them explicitly, and only when you actually want to verify against a live service. Tests that lack their required credentials should **skip**, not fail, so the tier is safe to run with only the keys you happen to have.

Here the "live service" is a **Naoqi**: a headless naoqi-sim by default (`NAOQI_E2E_TARGET` unset or `sim`; one sim per run; it needs Docker and `uv run naoqi-sim fetch-and-build-images` once, and the tier skips without them unless `NAOQI_E2E_TARGET=sim` is set), or a **real Nao robot** (`NAOQI_E2E_TARGET=real`, address in `NAOQI_E2E_IP`) — see [testing.md](specs/testing.md) "Live tier: the target". The fast tier runs on the `fake` backend (`FakeNaoqiRobot`, reached through `bridge.robot`), a stub `qi` module or a stubbed naoqi-sim — never a real robot or a real sim.

## Implementation plans

- Write implementation plans as files in the [plans](plans/) folder.
- Name each file `YYYYMMDDHHmm_plan-title.md`: a compact date-time prefix, then an underscore, then a kebab-case title (words separated by `-`).
  - Example: `202607201830_world-registry-refactor.md`
- Give each plan a `**Status:**` line just under its title (`Todo`/`In progress`/`Done`) and add a row for it to [plans/_index.md](plans/_index.md). Keep both current as work progresses (see "Keeping statuses current" above).
- Start from [plans/_plan-template.md](plans/_plan-template.md).

## Verification

After any code change, run linting, type checking, and tests, and fix any failures before considering the work done.

CI ([ci.md](specs/ci.md)) runs the same gate — lint, format check, type check, fast tier — on every pull request and push to `main`.

## Commands

```
uv sync --dev
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```
