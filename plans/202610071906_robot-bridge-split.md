# Robot / bridge split

**Status:** Done

Implements `specs/robot.md` (new) and `specs/bridge.md` (formerly `nao-api.md`), and updates `specs/nao-mcp-server.md` and `specs/nao-websocket-server.md` to sit on top of them. The architecture is a robot seam with `real` / `fake` backends, plus a bridge that owns the lifecycle and verbs. It also delivers every step of [202610071850_existing-code-to-green.md](202610071850_existing-code-to-green.md), since every module was being rewritten anyway.

## Scope

- `src/nao_bridge/robot.py` (new) — `NaoRobot` Protocol, `QiNaoRobot`, `FakeNaoRobot` with a `packages2`-shaped package list, `build_robot`, `RobotConnectionError`.
- `src/nao_bridge/bridge.py` (was `nao_api.py`) — `NaoBridge` with the `start`/`stop`/`async with` lifecycle, the pure `build_catalog` classifier, `bool` verbs with no fake-mode branches, running-item tracking, and stream marshalling. Fixes `stop_expressive_reaction`.
- `src/nao_bridge/__init__.py` — front-door re-exports.
- `src/nao_bridge/nao_mcp_server.py` — `NaoBridge`, package imports, one loop (`async with bridge` around `run_stdio_async`), and `add_tool(fn)` so docstrings become descriptions rather than titles.
- `src/nao_bridge/nao_websocket_server.py` — `NaoBridge`, package imports, async-typed command map, kept references to command tasks, guarded server close, sync `main()`.
- `pyproject.toml` — `nao-mcp-server` / `nao-websocket-server` console scripts.
- `tests/test_robot.py`, `tests/test_bridge.py`, `tests/test_nao_mcp_server.py`, `tests/test_nao_websocket_server.py` (new); `tests-e2e/test_real_robot.py` (new, skips without `qi` / `NAO_IP`).
- `AGENTS.md` project map, `specs/*`, `README.md`.

## Steps

1. Write `robot.md` and rewrite `bridge.md`; point the server specs at `NaoBridge`.
2. Build the seam: the Protocol, `QiNaoRobot` (lazy `qi` import, no silent fallback to fake, 10 connection tries, lazily cached services), and `FakeNaoRobot` (recording, package list, interruptible behavior runs, `touch` / `emit_audio`).
3. Rebuild `NaoAPI` as `NaoBridge` on the seam: catalog classification moves to `build_catalog`, the `fake_robot` checks disappear, and verbs share the `_act` / `_play` / `_stop` helpers.
4. Port both servers. Move `logging.basicConfig` into their `main()`.
5. Add the fast-tier tests and the live smoke test; add the console scripts; update README and the project map.

## Verification

`uv run ruff check .` and `uv run ruff format --check .` are clean. `uv run pyright` reports 0 errors (from 82). `uv run pytest` passes 42 tests, stable over repeated runs. `uv run pytest tests-e2e` skips cleanly without `qi`. Both console scripts start; `nao-mcp-server --fake-robot` answers `tools/list` over stdio, and `--ip` without `qi` exits 1 with an install hint.
