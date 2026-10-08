# Existing code to green

**Status:** Done

> Delivered by [202610072000_robot-bridge-split.md](202610072000_robot-bridge-split.md): it rewrote every module this plan touches, so each step below was carried out there and verified by that plan's gates. The file names below are from before the split (`nao_api.py` is now `bridge.py` + `robot.py`).

Brings the pre-SDD code (retro-documented in `specs/nao-api.md`, `specs/nao-mcp-server.md`, `specs/nao-websocket-server.md`) through the Verification gate, and fixes the `stop_expressive_reaction` defect listed in `specs/nao-api.md` ("Known gaps" #1). Behavior otherwise stays as specced; no new features.

Baseline when the workflow was adopted: `ruff check` 33 findings, `pyright` 82 errors, no functional tests.

## Scope

- `src/nao_bridge/nao_api.py` — fix `stop_expressive_reaction`; type the Naoqi service handles so pyright accepts them (narrow `Optional` or a typed `Any` proxy); handle the `qi` missing-import; remove dead `async_api`; ruff fixes.
- `src/nao_bridge/nao_mcp_server.py` — package import (`from nao_bridge.nao_api import NaoAPI`); ruff fixes.
- `src/nao_bridge/nao_websocket_server.py` — package import; type `command_mapping` as async (`Callable[[Any], Awaitable[tuple[bool, Any]]]`); guard `websocket_server` before `wait_closed`; ruff fixes.
- `pyproject.toml` — `[project.scripts]` entry points (`nao-mcp-server`, `nao-websocket-server`).
- `README.md` — update launch commands (`uv run nao-mcp-server --fake-robot`, MCP client configs) and the `src/nao_mcp` → `src/nao_bridge` rename.
- `tests/test_nao_api.py` — fake-robot functional tests.
- `tests/test_nao_mcp_server.py`, `tests/test_nao_websocket_server.py` — adapter tests against a fake-mode `NaoAPI`.
- `specs/*.md` — add the new test files to each spec's `tests:` frontmatter; drop resolved "Known gaps".

## Steps

1. Switch sibling imports to package imports and add the console-script entry points; confirm both servers start with `--fake-robot`.
2. Fix `stop_expressive_reaction` to stop `current_expressive_reactions[reaction_type]`, with a test using a stub behavior manager that asserts the right name is stopped.
3. Resolve pyright errors (service-handle typing, async command map, optional guards, `qi` import with a targeted ignore).
4. Apply `ruff check --fix`, then address the rest (blind `except Exception` is intentional at the API boundary — use `# noqa: BLE001` with that justification rather than narrowing).
5. Write fast-tier tests: fake-mode catalog getters, unknown-id → `False`, fake actions → `True`; MCP tool status strings and JSON shapes; WebSocket `CommandEnded` for known/unknown commands and camelCase payloads.
6. Update README, spec `tests:` frontmatter; flip `specs/nao-api.md` to `Implemented` and remove its Known gap #1.

## Verification

`uv run ruff check .`, `uv run pyright`, and `uv run pytest` all clean; both servers start via their entry points in fake-robot mode. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
