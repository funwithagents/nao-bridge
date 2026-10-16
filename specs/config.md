---
code:
  - src/naoqi_bridge/config.py
  - src/naoqi_bridge/bridge.py
  - src/naoqi_bridge/naoqi_mcp_server.py
  - src/naoqi_bridge/naoqi_websocket_server.py
  - examples/configs/mcp-real.json
  - examples/configs/websocket-real.json
tests:
  - tests/test_config.py
  - tests/test_bridge.py
---

# Configuration

**Status:** Updated

## Purpose

One declarative description of *which robot and what to stream*. A `NaoqiBridge` is built from it, and each server wraps it in its own config. Today the same facts are spread over `NaoqiBridge` keyword arguments, server arguments and CLI flags. A config file makes a setup reproducible: switching from the robot to the fake becomes a one-word change in one file.

It covers the **backend**, the **robot connection**, the **sim** a `sim` backend runs ([sim.md](sim.md)), the **streams** and the **viewer** ([viewer.md](viewer.md)). Other blocks are open questions below.

## Core concepts / Decided

### `NaoqiBridgeConfig` — top-level structure

```json
{
  "backend": "real",
  "robot": { "ip": "192.168.1.42", "port": 9559, "connect_timeout_s": 5.0 },
  "streams": {
    "joints": { "enabled": false, "period_s": 0.2 },
    "audio": { "enabled": false, "channel": "front" },
    "cameras": {
      "top": { "enabled": false, "resolution": "qvga", "fps": 10 },
      "bottom": { "enabled": false, "resolution": "qvga", "fps": 10 }
    }
  },
  "sim": {
    "spawn": "auto",
    "config": {
      "naoqi": { "version": "2.1" },
      "viewer": { "headless": true }
    }
  },
  "viewer": { "enabled": true, "config": { "ghost": true } }
}
```

`sim` applies only on `"backend": "sim"`; on `real` (as here) it is checked and ignored. `viewer` opens a window mirroring the robot on `real` and `sim` ([viewer.md](viewer.md)).

```python
@dataclass
class NaoqiBridgeConfig:
    backend: Backend = "fake"         # "real" | "fake" | "sim"
    robot: RobotSettings = field(default_factory=RobotSettings)
    streams: StreamSettings = field(default_factory=StreamSettings)
    sim: SimSettings = field(default_factory=SimSettings)
    viewer: ViewerSettings = field(default_factory=ViewerSettings)

@dataclass
class RobotSettings:
    ip: str = ""
    port: int = 9559
    connect_timeout_s: float = 5.0   # the one connection attempt; a silent host would otherwise wait for the OS TCP timeout

@dataclass
class StreamSettings:
    joints: JointsStream = field(default_factory=JointsStream)  # enabled: bool = False, period_s: float = 0.2
    audio: AudioStream = field(default_factory=AudioStream)     # enabled: bool = False, channel: "front" | "rear" | "left" | "right" = "front"
    cameras: CameraStreams = field(default_factory=CameraStreams)  # top / bottom: CameraStream(enabled=False, resolution="qvga", fps=10) — camera.md

@dataclass
class SimSettings:
    spawn: SimSpawn = "auto"                 # "never" | "auto" | "always" (sim.md, "Own it or borrow it")
    config: NaoqiSimConfig | None = None     # naoqi-sim's own config; None: naoqi-sim's defaults

@dataclass
class ViewerSettings:
    enabled: bool = False                     # viewer.md, "Which robot it mirrors"
    config: NaoqiViewerConfig | None = None   # naoqi-viewer's own config, minus mode, headless and naoqi.url; None: its defaults
```

- Every block is optional. Missing blocks and fields take the defaults above. **A default is declared once**, on the dataclass field; the loaders read it from there (`dataclasses.fields`), so a default can't drift between direct construction and JSON.
- **The default backend is `fake`.** A real Nao has no usable default address, so `NaoqiBridgeConfig()` is valid and offline. A real robot always means an explicit config with `robot.ip`; a simulated one, `backend: "sim"`.

### The `sim` block

The `sim` block has two keys, mirroring `SimSettings`: the bridge's `spawn` ([sim.md](sim.md)) and `config`, which is exactly a naoqi-sim config file, so one pastes in unchanged and copies back out unchanged:

- `spawn` is checked here (one of the three values). `config` goes to naoqi-sim's own `NaoqiSimConfig.from_dict`, imported lazily from `naoqi_sim.config` (which needs neither `qi` nor Docker); absent, it is `None`, naoqi-sim's defaults. naoqi-sim's `ConfigError` carries its key path the same way ours does; the loader re-raises it as ours with `sim.config.` in front (`sim.config.viewer.scene`). Its rules are naoqi-sim's: unknown keys, types, ranges.
- **Without the `[sim]` extra** naoqi-sim can't check `config`. With `backend: "sim"` that's a `ConfigError` (key `backend`) naming `naoqi-bridge[sim]`; with another backend `sim.config` is accepted unchecked and `config` stays `None`, so a file that switches backends still loads on a platform without the extra.
- **On `real` and `fake`, `sim` is validated but not applied**, as `robot` on `fake`; on `sim`, `robot.ip` and `robot.port` are, and `robot.connect_timeout_s` applies (the qi connection to the sim).

### The `viewer` block

Specified in [viewer.md](viewer.md) ("Config: the `viewer` block"). In short: `enabled` is a switch; `config` is a naoqi-viewer `NaoqiViewerConfig` block, checked by naoqi-viewer's own loader (imported lazily from `naoqi_viewer.config`) with errors prefixed `viewer.config.`, except `mode`, `headless` and `naoqi.url`, which the bridge sets and which are a `ConfigError` here. Without naoqi-viewer installed, `viewer.enabled: true` on `real` or `sim` is a `ConfigError` on `viewer.enabled` naming `naoqi-bridge[viewer]`; on `fake` or disabled, `config` is accepted unchecked and stays `None`.

### Constructors and validation

- Every config class has the same three constructors: `from_dict(data)`, `from_json(text)` (parses, then calls `from_dict`), and `from_json_file(path)` (reads, then calls `from_json`; an invalid-JSON error names the path). All three share one validation path.
- Errors raise `ConfigError(ValueError)`, with a message that names the offending key path (e.g. `streams.joints.period_s`). A block's own checks raise `ConfigError(message, key=<field>)`, and each enclosing loader prefixes `key` with its own path; the message is never parsed to find the key.
- **Unknown keys are errors**, so a typo fails when the config loads.
- **Type and range checks:** `backend` ∈ `{"real", "fake", "sim"}`; `sim.spawn` ∈ `{"never", "auto", "always"}`; `robot.port` is a positive integer; `connect_timeout_s` and `period_s` are positive, finite numbers; `channel` is one of the four values; a camera's `resolution` is one of `qqvga` / `qvga` / `vga` / `4vga` and its `fps` an integer from 1 to 30 ([camera.md](camera.md)).
- **`robot.connect_tries` is gone.** The connection makes one attempt since libqi 3.1.8 ([robot.md](robot.md)), so a config that still sets it fails as an unknown key.
- **`real` needs `robot.ip`.** An empty IP is a `ConfigError` when the config loads.
- **On `fake`, `robot` is validated but not applied.** A config written for the robot runs offline by changing `backend` alone.
- `config.py` imports neither `qi` nor `mcp` nor `websockets`; `naoqi_sim.config` only inside the `sim` loader and `naoqi_viewer.config` only inside the `viewer` loader.

### Streams: config switches, bridge APIs

The callbacks (`on_touch`, `on_joints`, `on_audio`) are **removed**. The config decides which of the streams that cost something the bridge subscribes to on the robot, **eagerly** at `start()`; touch costs nothing and is always on. Each stream is then consumed through a bridge API that any number of consumers can use:

| Stream | Config | Bridge API | Model |
|---|---|---|---|
| touch | none: always on | `bridge.on_touch: Event[TouchEvent]`, with `TouchEvent(part, touched)` | `Event[T]` (`events.py`, specified in `events.md`): synchronous handlers, any number, emitted on the bridge's event loop |
| joints | `streams.joints.enabled`, `period_s` | `bridge.joints: Observable[JointsState | None]`, with `JointsState(names, angles, ts)` | `Observable[T]` (`observable.py`, specified in `observable.md`): `value`, `changes()` latest-wins, `wait_for` |
| audio | `streams.audio.enabled`, `channel` | `bridge.audio_input(preroll_s=0.0)` and `bridge.mic` | [microphone.md](microphone.md): one feed, a ring, any number of subscribers |
| cameras | `streams.cameras.top` / `.bottom`: `enabled`, `resolution`, `fps` | `bridge.cameras["top"]` / `["bottom"]`: `latest()`, `frames()`, `wait_for` | [camera.md](camera.md): one feed per camera, pulled at `fps`, the newest frame with the camera's pose on an `Observable` |

- **Touch has no switch.** It is three `ALMemory` subscribers that fire only when a sensor changes: no task, no bandwidth, nothing to save by leaving it off. `start()` subscribes it on every backend, so `on_touch` emits without configuration, and a handler that never fires means the sensor wasn't pressed, not a forgotten flag. `streams.touch` is an unknown key, so a config from before this rule fails at load, naming it.
- **Using a disabled stream's API raises `BridgeError`** at the call: joints, audio, cameras.
- Because nothing is a callback any more, a server's config can't contradict its code. The MCP server just leaves streams disabled.

### `NaoqiBridge` construction

- `NaoqiBridge(config: NaoqiBridgeConfig | Backend | None = None)`; with no argument it uses `NaoqiBridgeConfig()`. A bare backend string is shorthand for `NaoqiBridgeConfig(backend=...)`, so `NaoqiBridge("fake")` stays the one-liner. `NaoqiBridge("real")` alone is a `ConfigError` (no IP).
- `NaoqiBridge.from_dict(data)`, `from_json(text)` and `from_json_file(path)` build the config, then the bridge.
- The `ip=` / `port=` / `on_*=` keyword arguments are **removed**.
- `bridge.config` exposes the config, read-only.
- `build_robot(config)` replaces `build_robot(backend, ip=..., port=...)` ([robot.md](robot.md)), and `RealNaoqiRobot` takes `connect_timeout_s` from it.

### Server configs: `{"bridge": …, "server": …}`

Each server has its own config object, wrapping a `NaoqiBridgeConfig` under `bridge` next to its own settings object under `server`. Both use the same three constructors and the same `ConfigError` rules.

```json
// NaoqiWebsocketServerConfig
{
  "bridge": {
    "backend": "real",
    "robot": { "ip": "192.168.1.42" },
    "streams": { "joints": { "enabled": true }, "audio": { "enabled": true } }
  },
  "server": { "host": "", "port": 8002 }
}

// NaoqiMcpServerConfig
{
  "bridge": { "backend": "fake" },
  "server": { "transport": "stdio" }
}
```

- `NaoqiWebsocketServerConfig(bridge, server: WebsocketServerSettings(host="", port=8002))`. `host` is the bind address; empty (the default) means the host's LAN IP, found at start (`127.0.0.1` when there's no route out); `port` 0 means an OS-assigned port ([naoqi-websocket-server.md](naoqi-websocket-server.md)). Its bridge streams replace `--with-joints-data` / `--with-audio-data`; touch is always on, as on the bridge. The server subscribes to `on_touch`, follows `bridge.joints.changes()`, and drains one `audio_input()` per client.
- `NaoqiMcpServerConfig(bridge, server: McpServerSettings(transport="stdio" | "sse"))`.
- The `bridge` block is exactly a `NaoqiBridgeConfig`, so it can be copied between files. Each server config class lives in its server module; `NaoqiBridgeConfig` and `ConfigError` live in `config.py`.

### CLIs: `--config` only

- `naoqi-mcp-server --config path.json` and `naoqi-websocket-server --config path.json`. The `--fake-robot`, `--ip`, `--port`, `--websocket-port`, `--with-joints-data` and `--with-audio-data` flags are **removed**.
- Without `--config`, the server runs on its default config, which is the `fake` backend.
- A config error exits 2 with the `ConfigError` message. An unreachable robot, a sim that can't be started or borrowed ([sim.md](sim.md), "Errors"), or a viewer that can't launch (`ViewerError`, [viewer.md](viewer.md), "Errors"), exits 1.

### Example files

`examples/configs/` holds ready-to-use files kept in sync with this spec:
- `mcp-fake.json` and `mcp-real.json`
- `websocket-fake.json` and `websocket-real.json` (every stream on, the top camera at `qvga` 10 fps; the bottom camera present and off)
- `mcp-sim.json` and `websocket-sim.json` ([sim.md](sim.md), "Example files")
- `mcp-real.json` and `websocket-real.json` carry a disabled `viewer` block with the ghost on ([viewer.md](viewer.md), "Example files")

The README's Claude Desktop / Tiny Agents snippets point `--config` at them.

## Open questions

1. **More blocks.** Motion (posture speed and tries), session state (what the robot does at start/stop: eye colors, wake up, breathing, TTS language) and catalog rules (reaction tags, system packages, for other robots or Naoqi versions) are candidates for optional blocks. Deferred until needed; adding one doesn't break existing files.
