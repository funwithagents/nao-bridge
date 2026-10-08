# Bridge, MCP server and robot backend cleanups

**Status:** Done

Implements the small edits to `specs/bridge.md` (read-only tracking views, `TouchPart`, tolerant parsing, `BridgeError` not re-exported) and `specs/robot.md` (`close()` forgets links and sink; audio paths raise `RobotConnectionError`), plus internal cleanups with no spec impact.

## Scope

- `src/nao_bridge/bridge.py` — one `_Running` tracker for dances, body actions, apps and reactions (the reaction pair stops duplicating `_play` / `_stop`); `current_*` as read-only views; `_parse_behaviors` uses `.get` on the sub-behavior fields; `TouchPart` literal; `BridgeError` dropped from `__all__`.
- `src/nao_bridge/__init__.py` — exports `TouchPart`.
- `src/nao_bridge/nao_mcp_server.py` — `_status(ok, success, failure)` helper; the three list tools all sync; class docstring on the class.
- `src/nao_bridge/real_robot.py` — `subscribe_audio` / `unsubscribe_audio` go through `_service`'s session guard; `close()` clears `_touch_links` and `_audio_service_id`.
- `src/nao_bridge/robot.py` — stop re-exporting `Backend`.
- `tests/test_bridge.py`, `tests/test_real_robot.py` — tolerant parsing; audio subscribe while disconnected raises `RobotConnectionError`; `close()` then `connect()` leaves no stale links.

## Steps

1. Bridge tracker and views; parser; literal; exports.
2. MCP helper and consistency.
3. Real backend guard and close.
4. Tests.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` clean.
