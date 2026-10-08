# Spec and doc drift

**Status:** Done

Closes the editorial gaps between specs, README and code found in the 2026-10-08 review, plus the one dead API they revealed. Specs stay `Implemented`: the only code change (dropping `raw`, relative imports in the servers) lands in this same plan.

## Scope

- `README.md` — MCP tool list gains `get_app_list` / `run_app` / `stop_app`; pre-roll wording matches the 200-chunk ring.
- `specs/config.md` — `NaoBridge` constructor signature matches `bridge.md` and the code.
- `specs/_index.md`, `specs/microphone.md` — the ring is sized in chunks, not "2 s".
- `specs/bridge.md`, `src/nao_bridge/bridge.py` — the unused `raw` alias is removed.
- `specs/project.md`, `src/nao_bridge/nao_mcp_server.py`, `src/nao_bridge/nao_websocket_server.py` — one import style: relative imports inside the package.
- `specs/testing.md` — the isolation-fixture sentence describes what exists.

## Steps

1. Spec and README edits.
2. Remove `NaoBridge.raw`; switch the two servers to relative imports.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` clean; `tests/test_project_map.py` unchanged.
