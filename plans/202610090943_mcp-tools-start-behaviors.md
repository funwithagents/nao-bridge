# MCP behavior tools return once started

**Status:** Done

Implements the settled behavior in `specs/nao-mcp-server.md` ("Tool surface", "Behaviors return once started"), closing the analysis's C1 and the MCP spec's open question 1. `dance`, `expressive_reaction`, `body_action` and `run_app` no longer hold an MCP tool call until the behavior ends. Like the WebSocket server, the MCP server runs the bridge verb in its own task; the tool returns once the behavior is playing, or with the reason it couldn't start. The agent gets `stop_dance`, `stop_expressive_reaction`, `stop_body_action` and `get_running` to follow and end what it started. It leaves out:
- any bridge change: its verbs still await the behavior's end;
- the rest of the WebSocket server's verbs (`stop_say`, eyes, awareness, breathing, raw behaviors), which stay unexposed;
- rejecting a second run of an item already playing (B5). Until then, a second `dance` of a dance already playing is seen as "playing" at once, and its own failure only reaches the log.

## Design

- **A run task per call, owned by the server.** `_start(verb_call, is_playing, success, failure)` creates a task for the blocking bridge verb, adds it to `self._runs` (strong references, as `ClientSession._tasks`), with a done-callback that discards it and logs a failure (`BridgeError` / `ValueError` / anything else) at error level, unless it's cancelled or its result was already reported to the tool.
- **Waiting for "playing or ended".** The tool loops on `asyncio.wait({task}, timeout=0.01)` until the task is done or `is_playing()` is true. `is_playing` reads the bridge's tracking (`dance_id in bridge.current_dances`, `reaction_type in bridge.current_expressive_reactions`, …), which the bridge sets after its checks pass, just before the robot call. When the task is done, its outcome goes through the same reporting as `_attempt`: an expected failure becomes `"Nao failed to …: <reason>"`, an unexpected exception propagates (a FastMCP tool error), success is `"Nao started …"`.
- **Shutdown:** `serve()` cancels and gathers the run tasks in a `finally` inside `async with bridge`, so they're gone before the bridge stops and closes the robot.
- **`get_running()`** returns `json.dumps({"dances": [...], "expressive_reactions": [...], "body_actions": [...], "apps": [...]})` from the bridge's `current_*`.
- **Stop tools** delegate to the bridge's stop verbs through `_attempt`.
- **Docstrings** of the four start tools say the call returns once the behavior has started, and point at `get_running` and the matching stop tool.

## Scope

- `specs/nao-mcp-server.md`: the tool table, the "not exposed" list trimmed, "Behaviors return once started", open question 1 removed. `Updated` while this plan is open, back to `Implemented` at the end.
- `src/nao_bridge/nao_mcp_server.py`: `_start` and the run tasks, the four tools rewired, `stop_dance` / `stop_expressive_reaction` / `stop_body_action` / `get_running` registered, `serve()` cancelling the runs.
- `tests/test_nao_mcp_server.py`: the tool set; with the fake's behaviors lasting 5 s, a `dance` call returns while the dance plays, `get_running` lists it, `stop_dance` ends it and `get_running` empties; failures before the start (motors off, unknown id) are still reported; a reaction through `stop_expressive_reaction`; a stop tool on an idle item; leaving `serve()` cancels the runs.
- `README.md`: the MCP tool list.
- `analysis/202610080900_robot-bridge-open-questions.md`: C1 removed, prune line updated.

## Steps

1. Spec edited, status `Updated` (file and index).
2. Server: `_start`, run tasks, tools, `serve()` shutdown.
3. Tests, README, analysis.
4. Verify, then this plan `Done` and the spec back to `Implemented`.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
