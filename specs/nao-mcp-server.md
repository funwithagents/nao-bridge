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
| `dance(dance_id)` | `dance` | status string |
| `get_expressive_reaction_types()` | `get_expressive_reaction_types` | JSON list of strings |
| `expressive_reaction(reaction_type)` | `expressive_reaction` | status string |
| `get_body_actions_list()` | `get_body_action_behaviors` | JSON list of `BehaviorInfos` |
| `body_action(body_action_id)` | `body_action` | status string |
| `get_app_list()` | `get_app_behaviors` | JSON list of `BehaviorInfos` |
| `run_app(app_id)` / `stop_app(app_id)` | `run_app` / `stop_app` | status string |

  Deliberately **not** exposed: `stop_say`, eyes color, basic awareness, breathing, raw `run_behavior`/`stop_behavior`, and stop-variants for dances/reactions/body actions.
- **Failure reporting:** an expected verb failure (`BridgeError` or `ValueError`, [bridge.md](bridge.md) "Errors") becomes the tool's result string, `"Nao failed to …: <reason>"`, so the model reads why and can act on it (`Nao failed to dance the dance with id 'macarena': unknown dance 'macarena' (known: …)`). Anything else is a bug, and FastMCP reports it as a tool error.
- **CLI:** the `nao-mcp-server` console script (also `python -m nao_bridge.nao_mcp_server`) takes `--config path.json` only; without it the server runs on its default config (the fake). An invalid config exits 2 with the `ConfigError` message. It configures logging (stderr, since stdout carries the stdio transport) and exits 1 if the robot is unreachable. Ready-made files: `examples/configs/mcp-fake.json`, `mcp-real.json`.

## Open questions

1. **Long-running tools.** `dance`/`run_app`/`body_action` hold the tool call until the behavior ends; `stop_app` only helps if the client issues calls concurrently. Should there be stop tools for dances and body actions, or should these tools return immediately?
