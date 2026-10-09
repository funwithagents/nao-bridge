# Verbs raise why they failed

**Status:** Done

Implements the settled behavior in `specs/bridge.md` ("Action verb contract", "Catalog verbs and what's running", "Errors"), `specs/nao-mcp-server.md` ("Failure reporting") and `specs/nao-websocket-server.md` (`CommandEnded`, "Single client"). `NaoBridge` verbs stop returning `bool` and raise a reason the caller can act on, and both servers put that reason in front of their client. It closes bridge.md's open question 1 (analysis B1). Running the same item twice (B5) and long-running MCP tools (C1) are left out.

## Scope

- `src/nao_bridge/errors.py`: `NotRunningError`, `NotPlayingError` and `CommandFailedError`, all under `BridgeError`.
- `src/nao_bridge/bridge.py`: verbs return `None`. `_act` raises `NotRunningError` while stopped and re-raises a robot exception as `CommandFailedError` (chained); a posture not reached raises `CommandFailedError`. `_entry` looks up a catalog id after the running check and raises `ValueError` naming the known ids. `_stop` raises `NotPlayingError`. `robot` / `audio_input()` raise `NotRunningError`. Tracking kinds are lower-case, since they now name things in messages.
- `src/nao_bridge/__init__.py`: exports the three new errors.
- `src/nao_bridge/nao_mcp_server.py`: `_status(ok, …)` becomes `_attempt(action, …)`, which awaits the verb and returns `"<failure>: <reason>"` on `BridgeError` / `ValueError`.
- `src/nao_bridge/nao_websocket_server.py`: `Verb` returns `None`. `CommandEnded.message` is the error's own message for `BridgeError` / `ValueError`. A failed connect/disconnect ritual step is a warning and the ritual goes on (`_ritual_step`).
- `tests/test_bridge.py`, `tests/test_nao_mcp_server.py`, `tests/test_nao_websocket_server.py`, `tests-e2e/test_live_robot.py`: tests that asserted `bool` now assert errors, plus tests for the reasons each server reports.
- `README.md`, `specs/robot.md`, `specs/microphone.md`: the error contract, where they mention it.

## Steps

1. Error classes in `errors.py`, exported from the front door.
2. Bridge verbs and catalog verbs raise; tracking kinds renamed.
3. MCP `_attempt`; WebSocket verb type, `CommandEnded.message` and ritual steps.
4. Tests and docs.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean.
