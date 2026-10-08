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
> No Nao robot? No worries! 😅 If you don't have a Nao or if your setup isn't supported by the qi package builds (like Windows users), use the `fake` backend (`--fake-robot` on the servers): the API and servers run without actual hardware.
> See usage details below.

## Installation

The project is managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --dev
```

This installs the package and the `nao-mcp-server` / `nao-websocket-server` commands in `.venv`.

## Dependency with qi python package

The communication with a real Nao robot relies on the `qi` python package, which is not on PyPI:
- find the built package for your setup (MacOS or Linux, and Python version) in the [latest Release](https://github.com/funwithagents/libqi-python/releases) of our [fork](https://github.com/funwithagents/libqi-python) of the [official libqi-python repository](https://github.com/aldebaran/libqi-python) (which is no longer maintained)
- currently compatible with MacOS arm64 and Linux architectures
- download the matching .whl file
- install it in the project environment: `uv pip install path/to/download/wheel.whl`

> [!WARNING]
> Without `qi`, the `real` backend fails to connect with an explicit error. It no longer silently switches to fake mode: ask for the fake backend explicitly.

## NaoBridge

The high-level async API to drive Nao.

### Usage

```python
import asyncio
from nao_bridge import NaoBridge


async def main():
    async with NaoBridge("real", ip="<nao-ip>") as bridge:  # or NaoBridge("fake")
        await bridge.wake_up()
        await bridge.say("Hello!")
        dances = bridge.get_dance_behaviors()
        await bridge.dance(dances[0].id)
        await bridge.rest()


asyncio.run(main())
```

`NaoBridge(backend="real", *, ip="", port=9559, on_touch=None, on_joints=None, on_audio=None)`:
- **`backend`**: `"real"` for a robot (needs `qi`), `"fake"` for the offline stand-in
- **`ip`** / **`port`**: the robot's address (default port 9559)
- **`on_touch`**: if set, called when Nao is touched: `async def on_touch(key, value)`, where `key` is the part touched (`FrontTactilTouched`, `MiddleTactilTouched`, `RearTactilTouched`) and `value` is 0 or 1
- **`on_joints`**: if set, called every 0.2 s with the robot's joints: `async def on_joints(joints_names, joints_angles)` (angles in radians)
- **`on_audio`**: if set, called with each microphone buffer: `async def on_audio(rate, nbOfChannels, nbOfSamplesByChannel, bufferData)`, where `bufferData` is a base64 encoded string of 16 bits little endian samples

`async with` connects on entry and disconnects on exit; `await bridge.start()` / `await bridge.stop()` do the same for hosts with their own lifecycle hooks. `bridge.robot` gives access to the underlying robot object while running.

### APIs

Every action is `async` and returns `True` on success, `False` otherwise (it never raises).

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
    - run the server: `uv run nao-mcp-server --ip <nao-ip>`

- run the server on the fake backend
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the MCP server with `--fake-robot` ⇒ all the MCP tools will be available for execution, they will just do nothing real
  - `uv run nao-mcp-server --fake-robot`

### Usage with HuggingFace Tiny Agents

- create a dedicated folder, let's sat `nao-tiny-agent`
- add a `PROMPT.md` file with a prompt like this:

```
You are in charge of the behavior of Nao, a robot connected on the network. Nao is a fun and witty robot from Aldebaran.
Your role it to answer to my inputs through Nao, using the provided tools.
I will not see your answers except when using Nao tools. So always make sure to call Nao say tool for the answers.
```
- add a `agent.json` file with your configuration

For a real robot:
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
            "--ip", "<nao-ip>"
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
            "--fake-robot"
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

For a real robot:
```json
"mcpServers": {
  "nao-mcp": {
    "command": "uv",
    "args": [
      "--directory", "path/to/repo", "run", "nao-mcp-server",
      "--ip", "<nao-ip>"
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
      "--fake-robot"
    ]
  }
}
```

- start Claude Desktop
> [!WARNING]
> Due to a log displayed at the start of the MCP server (in LibQi), Claude Desktop may show an error message ("MCP nao-mcp: Unexpected token ...").
> This log is harmless and the MCP server is running properly.
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
- **`dance`**: Make the robot dance
- **`get_expressive_reaction_types`**: Get the list of available reaction types, needed before calling the expressive_reaction tool
- **`expressive_reaction`**: Make Nao react expressively to a specific emotion/situation
- **`get_body_actions_list`**: Get the list of available body actions, needed before calling the body_action tool
- **`body_action`**: Make Nao perform an action with its body

## Nao websocket server

A server to communicate with NaoBridge over the network via websocket.
It provides access to all NaoBridge features through websocket messages in JSON format.

### Usage

- run the server with a real Nao robot
    - connect your Nao to your network
    - retrieve its IP address (by pressing its torso button) ⇒ `<nao-ip>`
    - run the server: `uv run nao-websocket-server --ip <nao-ip> (--with-joints-data) (--with-audio-data)`

- run the server on the fake backend
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the server with `--fake-robot` ⇒ all communication with the server will work but will just do nothing real
  - `uv run nao-websocket-server --fake-robot`

### Messages

> [!NOTE]
> The full protocol (envelope, commands and their data, streamed events) is described in [specs/nao-websocket-server.md](specs/nao-websocket-server.md).