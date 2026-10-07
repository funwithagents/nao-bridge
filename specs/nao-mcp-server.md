---
code:
  - src/nao_bridge/nao_mcp_server.py
tests:
---

# Nao MCP server

**Status:** Implemented

> Retro-documented from existing code when the SDD workflow was adopted.

## Purpose

Lets an LLM agent (Claude Desktop, HuggingFace Tiny Agents, any MCP client) drive Nao by calling tools. It is a thin adapter: every tool delegates to one [NaoAPI](nao-api.md) method and turns its result into a short natural-language status string the model can read.

## Core concepts / Decided

- **Runtime:** `NaoMcpServer(fake_robot, nao_ip, nao_port)` builds a `NaoAPI` with **no** touch/joints/audio callbacks (MCP is request/response; no streams) and a `mcp.server.fastmcp.FastMCP("Nao")` server. Requires the **v1** `mcp` SDK (`mcp<2`; v2 renamed FastMCP).
- **Startup:** `run(transport="stdio")` first runs `NaoAPI.connect()` in its own event loop; if that fails, the server does not start and `run` returns `False`. Otherwise it serves on the given transport (`stdio` default, `sse` supported).
- **Tool registration:** each tool is a server method registered under its own name with its docstring as the description. Docstrings are the prompt the model sees, so they encode usage order ("call `wake_up` first", "call `get_dance_list` before `dance`").
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
- **Failure reporting:** tools never raise; a `False` from `NaoAPI` becomes a "Nao failed to …" string.
- **CLI:** `main()` parses `--fake-robot`, `--ip`, `--port` (default 9559) and calls `run()` on stdio. Launched as a script (`python src/nao_bridge/nao_mcp_server.py …`) per the README.

## Open questions

1. **Long-running tools.** `dance`/`run_app`/`body_action` block the tool call until the behavior ends; `stop_app` can only help if the client issues concurrent calls. Expose stop tools for dances/body actions, or return immediately?
2. **Launch command.** Script-style launch relies on sibling imports (`from nao_api import …`); moving to package imports changes it to `python -m nao_bridge.nao_mcp_server` (see the cleanup plan).
3. **libqi startup log** on stdout can make Claude Desktop show a spurious parse error (README warning) — redirect it to stderr?
