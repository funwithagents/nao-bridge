---
code:
  - src/nao_bridge/config.py
  - src/nao_bridge/bridge.py
  - src/nao_bridge/nao_mcp_server.py
  - src/nao_bridge/nao_websocket_server.py
tests:
  - tests/test_config.py
  - tests/test_bridge.py
---

# Configuration

**Status:** Implemented

## Purpose

One declarative description of *which robot and what to stream*. A `NaoBridge` is built from it, and each server wraps it in its own config. Today the same facts are spread over `NaoBridge` keyword arguments, server arguments and CLI flags. A config file makes a setup reproducible: switching from the robot to the fake becomes a one-word change in one file.

The first version deliberately covers only the **backend**, the **robot connection** and the **streams**. Other blocks are open questions below.

## Core concepts / Decided

### `NaoBridgeConfig` — top-level structure

```json
{
  "backend": "real",
  "robot": { "ip": "192.168.1.42", "port": 9559, "connect_tries": 10, "connect_timeout_s": 5.0 },
  "streams": {
    "touch": { "enabled": true },
    "joints": { "enabled": false, "period_s": 0.2 },
    "audio": { "enabled": false, "channel": "front" }
  }
}
```

```python
@dataclass
class NaoBridgeConfig:
    backend: Backend = "fake"         # "real" | "fake"
    robot: RobotSettings = field(default_factory=RobotSettings)
    streams: StreamSettings = field(default_factory=StreamSettings)

@dataclass
class RobotSettings:
    ip: str = ""
    port: int = 9559
    connect_tries: int = 10
    connect_timeout_s: float = 5.0   # per attempt; a silent host would otherwise wait for the OS TCP timeout

@dataclass
class StreamSettings:
    touch: TouchStream = field(default_factory=TouchStream)     # enabled: bool = False
    joints: JointsStream = field(default_factory=JointsStream)  # enabled: bool = False, period_s: float = 0.2
    audio: AudioStream = field(default_factory=AudioStream)     # enabled: bool = False, channel: "front" | "rear" | "left" | "right" = "front"
```

- Every block is optional. Missing blocks and fields take the defaults above. **A default is declared once**, on the dataclass field; the loaders read it from there (`dataclasses.fields`), so a default can't drift between direct construction and JSON.
- **The default backend is `fake`.** A real Nao has no usable default address, so `NaoBridgeConfig()` is valid and offline. A real robot always means an explicit config with `robot.ip`.

### Constructors and validation

- Every config class has the same three constructors: `from_dict(data)`, `from_json(text)` (parses, then calls `from_dict`), and `from_json_file(path)` (reads, then calls `from_json`; an invalid-JSON error names the path). All three share one validation path.
- Errors raise `ConfigError(ValueError)`, with a message that names the offending key path (e.g. `streams.joints.period_s`). A block's own checks raise `ConfigError(message, key=<field>)`, and each enclosing loader prefixes `key` with its own path; the message is never parsed to find the key.
- **Unknown keys are errors**, so a typo fails when the config loads.
- **Type and range checks:** `backend` ∈ `{"real", "fake"}`; `robot.port` and `connect_tries` are positive integers; `connect_timeout_s` and `period_s` are positive, finite numbers; `channel` is one of the four values.
- **`real` needs `robot.ip`.** An empty IP is a `ConfigError` when the config loads.
- **On `fake`, `robot` is validated but not applied.** A config written for the robot runs offline by changing `backend` alone.
- `config.py` imports neither `qi` nor `mcp` nor `websockets`.

### Streams: config switches, bridge APIs

The callbacks (`on_touch`, `on_joints`, `on_audio`) are **removed**. The config decides what the bridge subscribes to on the robot, **eagerly** at `start()`. Each stream is then consumed through a bridge API that any number of consumers can use:

| Stream | Config | Bridge API | Model |
|---|---|---|---|
| touch | `streams.touch.enabled` | `bridge.on_touch: Event[TouchEvent]`, with `TouchEvent(part, touched)` | `Event[T]` (`events.py`, specified in `events.md`): synchronous handlers, any number, emitted on the bridge's event loop |
| joints | `streams.joints.enabled`, `period_s` | `bridge.joints: Observable[JointsState | None]`, with `JointsState(names, angles, ts)` | `Observable[T]` (`observable.py`, specified in `observable.md`): `value`, `changes()` latest-wins, `wait_for` |
| audio | `streams.audio.enabled`, `channel` | `bridge.audio_input(preroll_s=0.0)` and `bridge.mic` | [microphone.md](microphone.md): one feed, a ring, any number of subscribers |

- **Using a disabled stream's API raises `BridgeError`.** For joints and audio that's at the call. For touch, `on_touch` always exists and simply never emits.
- Because nothing is a callback any more, a server's config can't contradict its code. The MCP server just leaves streams disabled.

### `NaoBridge` construction

- `NaoBridge(config: NaoBridgeConfig | Backend | None = None)`; with no argument it uses `NaoBridgeConfig()`. A bare backend string is shorthand for `NaoBridgeConfig(backend=...)`, so `NaoBridge("fake")` stays the one-liner. `NaoBridge("real")` alone is a `ConfigError` (no IP).
- `NaoBridge.from_dict(data)`, `from_json(text)` and `from_json_file(path)` build the config, then the bridge.
- The `ip=` / `port=` / `on_*=` keyword arguments are **removed**.
- `bridge.config` exposes the config, read-only.
- `build_robot(config)` replaces `build_robot(backend, ip=..., port=...)` ([robot.md](robot.md)), and `RealNaoRobot` takes `connect_tries` from it.

### Server configs: `{"bridge": …, "server": …}`

Each server has its own config object, wrapping a `NaoBridgeConfig` under `bridge` next to its own settings object under `server`. Both use the same three constructors and the same `ConfigError` rules.

```json
// NaoWebsocketServerConfig
{
  "bridge": {
    "backend": "real",
    "robot": { "ip": "192.168.1.42" },
    "streams": { "touch": { "enabled": true }, "joints": { "enabled": true }, "audio": { "enabled": true } }
  },
  "server": { "host": "", "port": 8002 }
}

// NaoMcpServerConfig
{
  "bridge": { "backend": "fake" },
  "server": { "transport": "stdio" }
}
```

- `NaoWebsocketServerConfig(bridge, server: WebsocketServerSettings(host="", port=8002))`. `host` is the bind address; empty (the default) means the host's LAN IP, found at start (`127.0.0.1` when there's no route out); `port` 0 means an OS-assigned port ([nao-websocket-server.md](nao-websocket-server.md)). Its bridge streams replace `--with-joints-data` / `--with-audio-data`. Touch is no longer forced on: it's on when the config says so. The server subscribes to `on_touch`, follows `bridge.joints.changes()`, and drains one `audio_input()` per client.
- `NaoMcpServerConfig(bridge, server: McpServerSettings(transport="stdio" | "sse"))`.
- The `bridge` block is exactly a `NaoBridgeConfig`, so it can be copied between files. Each server config class lives in its server module; `NaoBridgeConfig` and `ConfigError` live in `config.py`.

### CLIs: `--config` only

- `nao-mcp-server --config path.json` and `nao-websocket-server --config path.json`. The `--fake-robot`, `--ip`, `--port`, `--websocket-port`, `--with-joints-data` and `--with-audio-data` flags are **removed**.
- Without `--config`, the server runs on its default config, which is the `fake` backend.
- A config error exits 2 with the `ConfigError` message. An unreachable robot still exits 1.

### Example files

`examples/configs/` holds ready-to-use files kept in sync with this spec:
- `mcp-fake.json` and `mcp-real.json`
- `websocket-fake.json` and `websocket-real.json` (all three streams on)

The README's Claude Desktop / Tiny Agents snippets point `--config` at them.

## Open questions

1. **More blocks.** Motion (posture speed and tries), session state (what the robot does at start/stop: eye colors, wake up, breathing, TTS language) and catalog rules (reaction tags, system packages, for other robots or Naoqi versions) are candidates for optional blocks. Deferred until needed; adding one doesn't break existing files.
2. **A `sim` backend** for a locally simulated Naoqi: `backend` gains `"sim"`, probably defaulting `robot.ip` to `127.0.0.1`. Deferred until that simulator exists.
