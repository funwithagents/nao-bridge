# Nao MCP - Robot Interaction API & Servers

This repository provides a set of tools to communicate with Nao robots and their API (it should work with any robot running Naoqi, the OS embedded in all Aldebaran robots).
The focus is on providing interactive high-level APIs to enable AI agent-based interactions with the robot.

It contains:
- [NaoAPI](https://github.com/funwithagents/nao-mcp/src/nao_bridge/nao_api.py): a wrapper to simplify connection to Nao and access its API
- [Nao MCP server](https://github.com/funwithagents/nao-mcp/src/nao_bridge/nao_websocket_server.py): a MCP server to communicate with NaoAPI
- [Nao websocket server](https://github.com/funwithagents/nao-mcp/src/nao_bridge/nao_websocket_server.py): a websocket server to communicate with NaoAPI

> [!IMPORTANT]
> This has only been tested with Naoqi 2.1.4.13 on a Nao v5.
> While the Qi package should work fine with more recent versions of Naoqi, the Naoqi API used here might have evolved since version 2.1.4.13. To test and add compatibility, we would need a Nao v6 robot (or even a Pepper robot) ! 🙂

> [!NOTE]
> No Nao robot? No worries! 😅 If you don't have a Nao or if your setup isn't supported by the qi package builds (like Windows users), all the provided classes include a "fake robot" mode that lets you use the API and servers without actual hardware. 
> See usage details below.

## Dependency with qi python package

The communication with a real Nao robot relies on the `qi` python package:
- find the built package for your setup (MacOS or Linux, and Python version) in the [latest Release](https://github.com/funwithagents/libqi-python/releases) of our [fork](https://github.com/funwithagents/libqi-python) of the [official libqi-python repository](https://github.com/aldebaran/libqi-python) (which is no longer maintained)
- currently compatible with MacOS arm64 and Linux architectures
- download the matching .whl file
- install it in your Python environment: `pip install path/to/download/wheel.whl`

## NaoAPI

A wrapper to simplify connection to Nao and access its API

### Usage

The NaoAPI class allows you to connect with a Nao and communicate with its API.
To do so:
- create a NaoAPI object:
  ```Python
  nao_api = NaoAPI(fake_robot,
                   memory_callback_touch,
                   joints_callback,
                   audio_callback,
                   nao_ip, nao_port)
  ```
  - **`fake_robot`**: boolean, whether or not you want to connect in "fake robot" mode
  - **`memory_callback_touch`**: if not None, this callback will be triggered when Nao is touched. Expected function definition is `async def memory_callback_touch(key, value)`, where `key` corresponds to the part touched and `value` is 0 or 1
  - **`joints_callback`**: if not None, will enable the joints data retrieval from Nao and this callback will be triggered periodically with the joints data of the robot. Expected function definition is `async def joints_callback(joints_names, joints_angles)` where `joint_names` is an array of strings with the names of the joints and `joints_angles` is an array of floats with the corresponding angles (in radians)
  - **`audio_callback`**: Callable[[str, float], None], if not None, will enable audio retrieval from Nao's microphone and this callback will be triggered with new audio buffer data. Expected function definition is `async def audio_callback(rate, nbOfChannels, nbOfSamplesByChannel, bufferData)` where `rate` is the frequency, `nbOfChannels` the number of channels, `nbOfSamplesByChannel` the number of samples per channel and `bufferData` a base64 encoded string from 16 bits little endian sound samples
  - **`nao_ip`**: the IP of the robot
  - **`nao_port`**: the port to communicate with the robot (default is 9559)

- initialize the connection with the robot (or fake robot)
  ```Python
  nao_connected = await self.nao_api.connect()
  ```

### APIs
- **`async def set_tts_language(self, language: str)`**: Set the text-to-speech language
- **`async def say(self, text: str)`**: Make the robot say something
- **`async def stop_say(self)`**: Stop the robot talking
- **`async def wake_up(self)`**: Enable robot motors
- **`sync def rest(self)`**: Disable robot motors
- **`sync def stand_up(self)`**: Make the robot stand up
- **`async def sit_down(self)`**: Make the robot sit down
- **`async def change_eyes_color(self, color: str)`**: Change the color of the robot's eyes
- **`async def set_basic_awareness_state(self, enabled: bool, engagement_mode: str, tracking_mode: str)`**: Set the basic awareness state of the robot
- **`async def set_breathing_enabled(self, enabled: bool, chain_name: str)`**: Enable or disable breathing for a specific chain
- **`def get_dance_behaviors(self) -> list[BehaviorInfos]`**: Retrieve the list of available dances, needed to call `dance` with right info
- **`async def dance(self, dance_id: str)`**: Make the robot execute a specific dance with given dance_id (from list of available dances)
- **`async def stop_dance(self, dance_id: str)`**: Make the robot stop a running dance with given dance_id (from list of available dances)
- **`def get_expressive_reaction_types(self) -> list[str]`**: Retrieve the list of available expressive reaction types, needed to call `expressive_reaction` with right info
- **`async def expressive_reaction(self, reaction_type: str)`**: Make the robot play an expressive reaction for a given reaction_type (from list of available types)
- **`async def stop_expressive_reaction(self, reaction_type: str)`**: Make the robot stop a running expressive reaction for a given reaction_type (from list of available types)
- **`def get_body_action_behaviors(self) -> list[BehaviorInfos]`**: Retrieve the list of available body actions, needed to call `body_action` with right info
- **`async def body_action(self, body_action_id: str)`**: Make the robot execute a specific action with its body for a given body_action_id (from list of available body actions)
- **`async def stop_body_action(self, body_action_id: str)`**: Make the robot stop a running body action for a given body_action_id (from list of available body actions)

> [!NOTE]
> In fake robot mode, the functions `get_dance_behaviors`, `get_expressive_reaction_types` and `get_body_action_behaviors` return some (fake) data to be able to have the needed information to call the functions `dance`, `expressive_reaction` and `body_action`

## Nao MCP server

A MCP server linked to NaoAPI.

### Usage

- run the MCP server with a real Nao robot
    - connect your Nao to your network
    - retrieve its IP address (by pressing its torso button) ⇒ `<nao-ip>`
    - run the server: `python nao_mcp_server.py --ip <nao-ip>`

- run the server in "fake robot" mode
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the MCP server in "fake robot" mode ⇒ all the MCP tools will be available for execution, they will just do nothing real
  - `python nao_mcp_server.py --fake-robot`

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
          "command": "path/to/pythonvenv/bin/python",
          "args": [
            "path/to/repo/src/nao_bridge/nao_mcp_server.py",
            "--ip", "<nao-ip>"
          ]
        }
      }
    ]
}
```

For fake robot mode:
```json
{
    "model": "Qwen/Qwen2.5-72B-Instruct",
    "provider": "nebius",
    "servers": [
      {
        "type": "stdio",
        "config": {
          "command": "path/to/pythonvenv/bin/python",
          "args": [
            "path/to/repo/src/nao_bridge/nao_mcp_server.py",
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
    "command": "path/to/pythonvenv/bin/python",
    "args": [
      "path/to/repo/src/nao_bridge/nao_mcp_server.py",
      "--ip", "<nao-ip>"
    ]
  }
}
```

For fake robot mode:
```json
"mcpServers": {
  "nao-mcp": {
    "command": "path/to/pythonvenv/bin/python",
    "args": [
      "path/to/repo/src/nao_bridge/nao_mcp_server.py",
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

A server to communicate with NaoAPI over the network via websocket.
It provides access to all NaoAPI features through websocket messages in JSON format.

### Usage

- run the server with a real Nao robot
    - connect your Nao to your network
    - retrieve its IP address (by pressing its torso button) ⇒ `<nao-ip>`
    - run the server: `python nao_websocket_server.py --ip <nao-ip> (--with-joints-data) (--with-audio-data)`

- run the server in "fake robot" mode
  - if you don't have a Nao robot or if your current setup is not compatible with the available qi packages, you can run the server in "fake robot" mode ⇒ all communication with the server will work but will just do nothing real
  - `python nao_websocket_server.py --fake-robot`

### Messages

> [!WARNING]
> Full description of the JSON for each message is still TODO.
> For now, you can check the message parsing in the `_apply_command_xxx` functions in [nao_websocket_server.py](https://github.com/funwithagents/nao-mcp/src/nao_bridge/nao_websocket_server.py)