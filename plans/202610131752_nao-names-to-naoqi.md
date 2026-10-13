# Nao names to Naoqi

**Status:** Done

The package became naoqi-bridge ([202610121745_rename-to-naoqi-bridge.md](202610121745_rename-to-naoqi-bridge.md)), but it kept the robot names (`NaoRobot`, `RealNaoRobot`, `FakeNaoRobot`, `NaoState`, `NAO_*`). This plan renames those code names to Naoqi, since the bridge targets any robot running Naoqi, and it clears the way for a `sim` backend. The real backend's class loses its `Real` prefix: `NaoqiRobot` is the robot over Naoqi, `FakeNaoqiRobot` its offline stand-in, and `AnyNaoqiRobot` the Protocol both implement. The only behavior change is the WebSocket protocol's first message, `NaoState` → `NaoqiState`, which bumps `protocolVersion` to 2.

**Kept:** "Nao" in prose where it means the physical robot ("Nao v5", "a real Nao", the README's agent prompts), the MCP server's advertised name `FastMCP("Nao")` and its tool result strings ("Nao said …": the agent drives a Nao), `<nao-ip>` and `nao-tiny-agent` in the README, the backend name `real`. `Done` plans are historical records and stay as written.

## Scope

Names, in replacement order (exact tokens, word-bounded):

| Old | New |
| --- | --- |
| `RealNaoRobot` | `NaoqiRobot` |
| `FakeNaoRobot` | `FakeNaoqiRobot` |
| `NaoRobot` (the Protocol) | `AnyNaoqiRobot` |
| `real_robot` (module, test module) | `naoqi_robot` |
| `NaoBehavior` (the catalog's flattened behavior) | `NaoqiBehavior` |
| `NaoState` | `NaoqiState` |
| `NAO_STATE` (a test constant) | `NAOQI_STATE` |
| `NAO_IP`, `NAO_PORT` | `NAOQI_E2E_IP`, `NAOQI_E2E_PORT` |
| `NAO_ALLOW_MOTION`, `NAO_INTERACTIVE` | `NAOQI_E2E_ALLOW_MOTION`, `NAOQI_E2E_INTERACTIVE` |
| `fake-nao-audio` (thread name) | `fake-naoqi-audio` |
| "Nao MCP server", "Nao websocket server" / "Nao WebSocket server" (the servers' display names) | "Naoqi MCP server", "Naoqi WebSocket server" |

Files:

- `src/naoqi_bridge/real_robot.py` → `src/naoqi_bridge/naoqi_robot.py`, `tests/test_real_robot.py` → `tests/test_naoqi_robot.py` (`git mv`)
- `src/naoqi_bridge/robot.py`, `fake_robot.py`, `bridge.py`, `microphone.py`, `naoqi_websocket_server.py` (`NaoqiState`, `PROTOCOL_VERSION = 2`), `naoqi_mcp_server.py` (module docstring)
- `tests/` and `tests-e2e/`: imports, names, the env vars
- `specs/`: `robot.md` (frontmatter paths, names), `naoqi-websocket-server.md` (`NaoqiState`, version 2), `testing.md` (env vars), `_overview.md`, `_index.md`, `config.md`, `bridge.md`, `microphone.md`, `project.md`, `ci.md`
- `AGENTS.md` (project map row, which `tests/test_project_map.py` checks; testing paragraph), `README.md` (names, protocol version), `.github/workflows/ci.yml` (comment), `analysis/` (names)
- `plans/_index.md`: this plan's row

Spec statuses: the spec edits land in the same commit as the code, so every `Implemented` spec stays `Implemented`.

## Steps

1. `git mv` the module and its test.
2. Replace the tokens in the table, in that order, across tracked files except `plans/2*.md` (`perl -pi -e 's/\bOld\b/New/g'`). The display names are replaced by hand.
3. `PROTOCOL_VERSION = 2`; the spec's "Protocol version" section and the README say why (the first message renamed).
4. Review the diff: no `Nao[A-Z]`, `NAO_` or `real_robot` left outside `Done` plans, prose about the robot untouched.
5. Lint, type check, tests (Verification). Commit on `main`.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` all clean (`tests/test_project_map.py` included).
- `git grep -n -P '\bNao[A-Z]|\bNAO_|real_robot|RealNao' -- ':!plans/2*'` returns nothing.
- `uv run pytest tests-e2e` without a robot: skips only, no errors.

Mark this plan `Done` here and in [_index.md](_index.md) once all pass.
