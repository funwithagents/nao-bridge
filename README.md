# Nao Bridge - Robot Interaction API & Servers

This repository provides a set of tools to communicate with Nao robots and their API (it should work with any robot running Naoqi, the OS embedded in all Aldebaran robots).
The focus is on providing interactive high-level APIs to enable AI agent-based interactions with the robot.

It contains:
- [NaoBridge](src/nao_bridge/bridge.py): the high-level async API to drive Nao, on top of a [robot seam](src/nao_bridge/robot.py) with a `real` backend (a Nao over `qi`) and a `fake` one (no hardware)
- [Nao MCP server](src/nao_bridge/nao_mcp_server.py): a MCP server exposing NaoBridge as tools for LLM agents
- [Nao websocket server](src/nao_bridge/nao_websocket_server.py): a websocket server to communicate with NaoBridge over the network

Design docs live in [specs/](specs/_index.md); contributor and agent instructions in [AGENTS.md](AGENTS.md).

> [!IMPORTANT]
> This has only been tested with Naoqi 2.1.4.13 on a Nao v5.
> While the Qi package should work fine with more recent versions of Naoqi, the Naoqi API used here might have evolved since version 2.1.4.13. To test and add compatibility, we would need a Nao v6 robot (or even a Pepper robot) ! 🙂

> [!NOTE]
> No Nao robot? No worries! 😅 If you don't have a Nao or if your platform has no `qi` wheel (like Windows), use the `fake` backend (the default; `examples/configs/*-fake.json` for the servers): the API and servers run without actual hardware.
> See usage details below.

## Installation

The project is managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --dev
```

This installs the package and the `nao-mcp-server` / `nao-websocket-server` commands in `.venv`.

## Dependency with qi python package

Communicating with a real Nao relies on the `qi` Python package. It comes from the GitHub releases of our [fork](https://github.com/funwithagents/libqi-python) of the [official libqi-python repository](https://github.com/aldebaran/libqi-python), which is no longer maintained. It is a declared dependency, so **`uv sync` installs it** on the platforms that have a wheel:

| Platform | `qi` | What runs |
|---|---|---|
| macOS arm64, Linux x86_64 (Python 3.12 or 3.13) | installed by `uv sync` | real robot and fake |
| Windows, macOS Intel, Linux arm64 | not available | fake only |

> [!WARNING]
> Without `qi`, the `real` backend fails to connect with an explicit error; it never silently switches to the fake. On a platform without a wheel, use the `fake` backend.

> [!NOTE]
> Install with `uv`: the wheel locations are uv settings (`[tool.uv.sources]`), which `pip` ignores.

## NaoBridge

The high-level async API to drive Nao.

### Usage

```python
import asyncio
from nao_bridge import NaoBridge


async def main():
    # NaoBridge("fake") for the offline robot
    bridge = NaoBridge.from_dict({"backend": "real", "robot": {"ip": "<nao-ip>"}})
    async with bridge:
        await bridge.wake_up()
        await bridge.say("Hello!")
        dances = bridge.get_dance_behaviors()
        await bridge.dance(dances[0].id)
        await bridge.rest()


asyncio.run(main())
```

### Configuration

The bridge is built from a `NaoBridgeConfig`, in code or from JSON (`NaoBridge.from_dict` / `from_json` / `from_json_file`). Every block is optional; the default is the offline fake with no streams:

```json
{
  "backend": "real",
  "robot": { "ip": "192.168.1.42", "port": 9559, "connect_tries": 10, "connect_timeout_s": 5.0 },
  "streams": {
    "touch": { "enabled": true },
    "joints": { "enabled": true, "period_s": 0.2 },
    "audio": { "enabled": true, "channel": "front" }
  }
}
```

- **`backend`**: `"fake"` (default, offline stand-in) or `"real"` (needs `qi` and `robot.ip`)
- **`robot`**: the robot's address, and how hard to try reaching it: up to `connect_tries` attempts of at most `connect_timeout_s` each, so a wrong address fails within 50 s by default. Validated but ignored on `fake`, so switching backend is a one-word change
- **`streams`**: which robot streams the bridge subscribes to; `channel` picks the microphone (`front`, `rear`, `left`, `right`)

A malformed config raises `ConfigError` naming the key (e.g. `streams.joints.period_s must be a positive, finite number`). Full reference: [specs/config.md](specs/config.md).

`async with` connects on entry and disconnects on exit; `await bridge.start()` / `await bridge.stop()` do the same for hosts with their own lifecycle hooks. `bridge.robot` gives access to the underlying robot object while running.

### Streams

Each enabled stream has its own API, open to any number of consumers:

```python
streams = {
    "touch": {"enabled": True},
    "joints": {"enabled": True},
    "audio": {"enabled": True},
}
async with NaoBridge.from_dict({"streams": streams}) as bridge:
    # touch events
    bridge.on_touch.subscribe(lambda event: print(event.part, event.touched))

    # the latest joints state
    pose = await bridge.joints.wait_for(lambda s: s is not None)
    print(dict(zip(pose.names, pose.angles)))

    # the microphone: int16 LE mono at 16 kHz, every chunk in order
    async for chunk in bridge.audio_input():
        ...  # feed your ASR
```

- **Touch**: `bridge.on_touch` is an event; handlers receive a `TouchEvent(part, touched)` on the event loop
- **Joints**: `bridge.joints` holds the latest `JointsState(names, angles, ts)` (radians): read `.value`, iterate `.changes()` (a slow reader skips to the latest), or `await .wait_for(predicate)`
- **Audio**: every `bridge.audio_input()` call is its own subscriber receiving every chunk; `preroll_s=` starts it in the past, as far as the ring of the last 200 chunks reaches (e.g. to hear the sentence that woke a wake-word detector); `bridge.mic.latest()` gives the newest chunk for level meters

### APIs

Every action is `async`, returns `None` on success and raises to say why it failed: `ValueError` for an id or reaction type the catalog doesn't hold (the message lists the known ones), `NotRunningError` before `start()`, `NotPlayingError` when stopping something that isn't playing, `MotorsOffError` when a verb that moves the body (`stand_up`, `sit_down`, `set_breathing_enabled(True, …)`, `run_behavior`, `dance`, `expressive_reaction`, `body_action`, `run_app`) finds the motors off (call `wake_up()` first; the fake starts with them off, like a robot at rest), `CommandFailedError` when the robot fails the command (the Naoqi error chained). The last three are `BridgeError`s, so `except (BridgeError, ValueError)` catches every expected failure.

- **`async def set_tts_language(self, language: str)`**: Set the text-to-speech language
- **`async def say(self, text: str)`**: Make the robot say something
- **`async def stop_say(self)`**: Stop the robot talking
- **`async def wake_up(self)`**: Enable robot motors
- **`async def rest(self)`**: Disable robot motors
- **`async def stand_up(self)`**: Make the robot stand up
- **`async def sit_down(self)`**: Make the robot sit down
- **`async def change_eyes_color(self, color: str)`**: Change the color of the robot's eyes
- **`async def set_basic_awareness_state(self, enabled: bool, engagement_mode: str, tracking_mode: str)`**: Set the basic awareness state of the robot
- **`async def set_breathing_enabled(self, enabled: bool, chain_name: str)`**: Enable or disable breathing for a specific chain
- **`async def run_behavior(self, behavior_name: str)`** / **`stop_behavior`**: Run / stop any installed behavior by name
- **`def get_dance_behaviors(self) -> list[BehaviorInfos]`**: Retrieve the list of available dances, needed to call `dance` with right info
- **`async def dance(self, dance_id: str)`**: Make the robot execute a specific dance with given dance_id (from list of available dances)
- **`async def stop_dance(self, dance_id: str)`**: Make the robot stop a running dance with given dance_id (from list of available dances)
- **`def get_expressive_reaction_types(self) -> list[str]`**: Retrieve the list of available expressive reaction types, needed to call `expressive_reaction` with right info
- **`async def expressive_reaction(self, reaction_type: str)`**: Make the robot play an expressive reaction for a given reaction_type (from list of available types)
- **`async def stop_expressive_reaction(self, reaction_type: str)`**: Make the robot stop a running expressive reaction for a given reaction_type (from list of available types)
- **`def get_body_action_behaviors(self) -> list[BehaviorInfos]`**: Retrieve the list of available body actions, needed to call `body_action` with right info
- **`async def body_action(self, body_action_id: str)`**: Make the robot execute a specific action with its body for a given body_action_id (from list of available body actions)
- **`async def stop_body_action(self, body_action_id: str)`**: Make the robot stop a running body action for a given body_action_id (from list of available body actions)
- **`def get_app_behaviors(self) -> list[BehaviorInfos]`**: Retrieve the list of installed apps, needed to call `run_app` with right info
- **`async def run_app(self, app_id: str)`** / **`stop_app`**: Run / stop an installed app

> [!NOTE]
> On the `fake` backend, the robot serves a fixed set of dances, reactions, body actions and apps, so the getters return data you can pass to `dance`, `expressive_reaction`, `body_action` and `run_app`.

## Nao MCP server

A MCP server linked to NaoBridge.

### Usage

- run the MCP server with a real Nao robot
    - connect your Nao to your network
    - retrieve its IP address (by pressing its torso button) ⇒ `<nao-ip>`
    - put it in a copy of [examples/configs/mcp-real.json](examples/configs/mcp-real.json) (`bridge.robot.ip`)
    - run the server: `uv run nao-mcp-server --config path/to/mcp-real.json`

- run the server on the fake backend
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the MCP server on the fake ⇒ all the MCP tools will be available for execution, they will just do nothing real
  - `uv run nao-mcp-server` (no config means the fake), or `--config examples/configs/mcp-fake.json`

A server config has a `bridge` block (the bridge's config above) and a `server` block (`transport`: `stdio` or `sse`).

### Usage with HuggingFace Tiny Agents

- create a dedicated folder, let's sat `nao-tiny-agent`
- add a `PROMPT.md` file with a prompt like this:

```
You are in charge of the behavior of Nao, a robot connected on the network. Nao is a fun and witty robot from Aldebaran.
Your role it to answer to my inputs through Nao, using the provided tools.
I will not see your answers except when using Nao tools. So always make sure to call Nao say tool for the answers.
```
- add a `agent.json` file with your configuration

For a real robot (with your copy of `mcp-real.json`):
```json
{
    "model": "Qwen/Qwen2.5-72B-Instruct",
    "provider": "nebius",
    "servers": [
      {
        "type": "stdio",
        "config": {
          "command": "uv",
          "args": [
            "--directory", "path/to/repo", "run", "nao-mcp-server",
            "--config", "path/to/mcp-real.json"
          ]
        }
      }
    ]
}
```

For the fake backend:
```json
{
    "model": "Qwen/Qwen2.5-72B-Instruct",
    "provider": "nebius",
    "servers": [
      {
        "type": "stdio",
        "config": {
          "command": "uv",
          "args": [
            "--directory", "path/to/repo", "run", "nao-mcp-server",
            "--config", "path/to/repo/examples/configs/mcp-fake.json"
          ]
        }
      }
    ]
}
```

- set your HuggingFace token: `export HF_TOKEN=<token>`
- run your tiny agent: `npx @huggingface/tiny-agents run ./nao-tiny-agent`

> [!NOTE]
> It works well when asking explicitly the agent to do actions on Nao like "Make Nao do xxx"
> However, when trying to have the agent answering as if it was Nao, it keeps forgetting to use the tool "say" to anwser to the user via Nao, and answers directly in text instead. Maybe it could be improved/avoided using a better prompt.


### Usage with Claude Desktop

- Add to your `claude_desktop_config.json`

For a real robot (with your copy of `mcp-real.json`):
```json
"mcpServers": {
  "nao-mcp": {
    "command": "uv",
    "args": [
      "--directory", "path/to/repo", "run", "nao-mcp-server",
      "--config", "path/to/mcp-real.json"
    ]
  }
}
```

For the fake backend:
```json
"mcpServers": {
  "nao-mcp": {
    "command": "uv",
    "args": [
      "--directory", "path/to/repo", "run", "nao-mcp-server",
      "--config", "path/to/repo/examples/configs/mcp-fake.json"
    ]
  }
}
```

- start Claude Desktop
- start a new conversation with a prompt like this one
```
You are incarnating Nao, a fun and witty robot from the company Aldebaran. You can only answer using the nao-mcp tools, no text output.  And when Nao speaks, use short answers.
```

### Tools

- **`set_tts_language`**: Change the language of Nao text to speech
- **`say`**: Make Nao say something
- **`wake_up`**: Enable Nao motors for action
- **`rest`**: Disable Nao motors
- **`stand_up`**: Make Nao stand up
- **`sit_down`**: Make Nao sit down
- **`get_dance_list`**: Get the list of available dances, needed before calling the dance tool
- **`dance`** / **`stop_dance`**: Make the robot start / stop a dance
- **`get_expressive_reaction_types`**: Get the list of available reaction types, needed before calling the expressive_reaction tool
- **`expressive_reaction`** / **`stop_expressive_reaction`**: Make Nao start / stop reacting expressively to a specific emotion/situation
- **`get_body_actions_list`**: Get the list of available body actions, needed before calling the body_action tool
- **`body_action`** / **`stop_body_action`**: Make Nao start / stop an action with its body
- **`get_app_list`**: Get the list of installed apps, needed before calling the run_app and stop_app tools
- **`run_app`** / **`stop_app`**: Make Nao start / stop an installed app
- **`get_running`**: What Nao is playing right now (dances, reactions, body actions, apps)

`dance`, `expressive_reaction`, `body_action` and `run_app` return as soon as the behavior has started (or with the reason it couldn't), like the WebSocket server's commands: the behavior goes on while the agent calls other tools, `get_running` says whether it's still playing, and the matching `stop_*` tool ends it.

## Nao websocket server

A server to communicate with NaoBridge over the network via websocket.
It provides access to all NaoBridge features through websocket messages in JSON format.

### Usage

- run the server with a real Nao robot
    - connect your Nao to your network
    - retrieve its IP address (by pressing its torso button) ⇒ `<nao-ip>`
    - put it in a copy of [examples/configs/websocket-real.json](examples/configs/websocket-real.json) (`bridge.robot.ip`), and choose the streams sent to the client in `bridge.streams`
    - run the server: `uv run nao-websocket-server --config path/to/websocket-real.json`

- run the server on the fake backend
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the server on the fake ⇒ all communication with the server will work but will just do nothing real
  - `uv run nao-websocket-server --config examples/configs/websocket-fake.json` (every stream on, the fake streams silent audio)

The `server` block sets the WebSocket `host` (the address to bind; empty, the default, means the machine's LAN IP, `"0.0.0.0"` every interface) and `port` (default 8002; `0` lets the OS pick).

### Messages

> [!NOTE]
> The full protocol (envelope, commands and their data, streamed events) is described in [specs/nao-websocket-server.md](specs/nao-websocket-server.md).