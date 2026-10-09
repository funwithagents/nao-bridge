---
code:
  - src/nao_bridge/nao_mcp_server.py
tests:
  - tests/test_nao_mcp_server.py
---

# Nao MCP server

**Status:** Implemented

## Purpose

Lets an LLM agent (Claude Desktop, HuggingFace Tiny Agents, any MCP client) drive Nao by calling tools. It's a thin adapter: each tool delegates to one [NaoBridge](bridge.md) verb and turns the result into a short natural-language status string the model can read.

## Core concepts / Decided

- **Config:** `NaoMcpServerConfig` is `{"bridge": NaoBridgeConfig, "server": McpServerSettings}`, with `McpServerSettings(transport: "stdio" | "sse" = "stdio")`. Both blocks are optional and share the loaders and `ConfigError` rules of [config.md](config.md). MCP is request/response, so its bridge normally enables no stream.
- **Runtime:** `NaoMcpServer(config=None)` (default: `NaoMcpServerConfig()`, the fake over stdio) builds a `NaoBridge(config.bridge)` and a `mcp.server.fastmcp.FastMCP("Nao")` server. It requires the **v1** `mcp` SDK (`mcp<2`; v2 renamed FastMCP).
- **One event loop, one session:** `serve()` runs `async with bridge:` around `run_stdio_async()` (or `run_sse_async()`, per `server.transport`). The bridge connects before serving and stops when the client leaves. `run()` wraps it in `asyncio.run`. If the robot can't be reached (`RobotConnectionError`), it logs the error and returns `False` without serving.
- **stdout belongs to the protocol.** Over stdio, fd 1 is the JSON-RPC channel, and native code writes to it directly: libqi's console log handler does from the first `qi.Session()` on (`[W] … qi.path.sdklayout: No Application was created…`), and `qi.logging` can't redirect it. So `serve()` enters `stdout_reserved_for_protocol()` *before* the bridge starts and leaves it after the bridge stops:
  - fd 1 points at stderr, so native writes land there and stay visible in the server's log;
  - `sys.stdout`, which the stdio transport wraps when it starts, is a private duplicate of the real stdout;
  - on exit, fd 1 and `sys.stdout` are restored.

  Only JSON-RPC reaches the client. The bridge library itself never touches process file descriptors; this is the stdio server's concern.
- **Tool registration:** each tool is a server method passed to `FastMCP.add_tool(fn)`, which takes the tool's **name from the method and its description from the docstring**. The tool title stays unset. (The earlier code passed the docstring positionally into the `title` slot.) Docstrings are the prompt the model sees, so they encode usage order ("call `wake_up` first", "call `get_dance_list` before `dance`").
- **Tool surface:**

| Tool | Delegates to | Returns |
|---|---|---|
| `set_tts_language(language)` | `set_tts_language` | status string |
| `say(text)` | `say` | status string |
| `wake_up()` / `rest()` | `wake_up` / `rest` | status string |
| `stand_up()` / `sit_down()` | `stand_up` / `sit_down` | status string |
| `get_dance_list()` | `get_dance_behaviors` | JSON list of `BehaviorInfos` (snake_case `asdict`) |
| `dance(dance_id)` / `stop_dance(dance_id)` | `dance` / `stop_dance` | status string |
| `get_expressive_reaction_types()` | `get_expressive_reaction_types` | JSON list of strings |
| `expressive_reaction(reaction_type)` / `stop_expressive_reaction(reaction_type)` | `expressive_reaction` / `stop_expressive_reaction` | status string |
| `get_body_actions_list()` | `get_body_action_behaviors` | JSON list of `BehaviorInfos` |
| `body_action(body_action_id)` / `stop_body_action(body_action_id)` | `body_action` / `stop_body_action` | status string |
| `get_app_list()` | `get_app_behaviors` | JSON list of `BehaviorInfos` |
| `run_app(app_id)` / `stop_app(app_id)` | `run_app` / `stop_app` | status string |
| `get_running()` | `current_dances`, `current_expressive_reactions`, `current_body_actions`, `current_apps` | JSON object `{"dances", "expressive_reactions", "body_actions", "apps"}`, each a list of ids (reaction types for reactions) |

  Deliberately **not** exposed: `stop_say`, eyes color, basic awareness, breathing, raw `run_behavior`/`stop_behavior`.
- **Behaviors return once started**, as the [WebSocket server](nao-websocket-server.md) runs each command in its own task. A dance, an app or a body action can last minutes, and most MCP clients issue one tool call at a time, so a tool that held the call until the behavior ended would leave the agent unable to do anything else, stop included. So `dance`, `expressive_reaction`, `body_action` and `run_app` start their (blocking) bridge verb as a task the server owns, then wait until **either** the item is playing (it appears in the bridge's `current_*` tracking) **or** the task has ended:
  - playing: the result is `"Nao started …"`, and the run goes on in the background;
  - ended with an expected failure (`BridgeError` / `ValueError`: unknown id, motors off, …): the usual `"Nao failed to …: <reason>"`;
  - ended successfully before it was seen playing (a behavior shorter than the wait's polling, e.g. the fast tier's instant fake): `"Nao started …"` too.

  A run that fails after it started is logged at error level with its reason; it's then gone from `get_running`. The server keeps its run tasks and cancels them when it stops serving, before the bridge stops (which closes the robot and so ends the behaviors). The model follows up with `get_running` and the `stop_*` tool of the same kind; the tools' docstrings say so. The bridge is unchanged: its verbs still await the behavior's end.
- **Failure reporting:** an expected verb failure (`BridgeError` or `ValueError`, [bridge.md](bridge.md) "Errors") becomes the tool's result string, `"Nao failed to …: <reason>"`, so the model reads why and can act on it (`Nao failed to dance the dance with id 'macarena': unknown dance 'macarena' (known: …)`). Anything else is a bug, and FastMCP reports it as a tool error.
- **CLI:** the `nao-mcp-server` console script (also `python -m nao_bridge.nao_mcp_server`) takes `--config path.json` only; without it the server runs on its default config (the fake). An invalid config exits 2 with the `ConfigError` message. It configures logging (stderr, since stdout carries the stdio transport) and exits 1 if the robot is unreachable. Ready-made files: `examples/configs/mcp-fake.json`, `mcp-real.json`.

## Open questions

None.
