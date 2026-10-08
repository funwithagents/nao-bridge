---
code:
  - src/nao_bridge/nao_websocket_server.py
tests:
  - tests/test_nao_websocket_server.py
---

# Nao WebSocket server

**Status:** Implemented

## Purpose

Gives non-MCP clients (a game engine, a web app, a custom agent loop) network access to [NaoBridge](bridge.md) over a JSON WebSocket protocol — commands in, results and live robot events (touch, joints, audio, logs) out. Like the MCP server, it is an adapter with no robot logic of its own.

## Core concepts / Decided

### Lifecycle

- **Config:** `NaoWebsocketServerConfig` is `{"bridge": NaoBridgeConfig, "server": WebsocketServerSettings}`, with `WebsocketServerSettings(port: int = 8002)` (1–65535). Both blocks are optional and share the loaders and `ConfigError` rules of [config.md](config.md). The bridge's `streams` decide which events the server streams to its client: none is forced on.
- `NaoWebsocketServer(config=None)` (default: `NaoWebsocketServerConfig()`, the fake with no streams) builds a `NaoBridge(config.bridge)`.
- `async start_connection()` starts the bridge and, when touch is enabled, subscribes its handler to `bridge.on_touch`. On `RobotConnectionError` it logs and returns `False`. Otherwise it serves on the host's **LAN IP** (found via a UDP socket towards 8.8.8.8) at `websocket_port`.
- `async stop_connection()` stops the bridge, disconnects the client, and closes the server.
- CLI: the `nao-websocket-server` console script (also `python -m nao_bridge.nao_websocket_server`) takes `--config path.json` only; without it the server runs on its default config. An invalid config exits 2 with the `ConfigError` message. It runs until Enter is pressed and exits 1 if the robot is unreachable. Ready-made files: `examples/configs/websocket-fake.json`, `websocket-real.json` (every stream on).

### Single client

Exactly one client at a time. A new connection closes the previous client (stopping its streams first).
- On client **connect** (when the robot is connected): eyes cyan, `wake_up`, breathing on for `Body`; then a `NaoState` message is sent and the client's streams start.
- On client **disconnect**: its streams stop, then eyes white, breathing off, `rest`.

**Streams per client session** (each only when enabled in the bridge config):
- **Touch:** the `bridge.on_touch` handler sends a `Touch` message for each event.
- **Joints:** a task follows `bridge.joints.changes()` and sends a `Joints` message per published sample. It is latest-wins, so a slow connection skips poses rather than lagging.
- **Audio:** a task drains one `bridge.audio_input()` subscriber and sends an `Audio` message per chunk, base64-encoding it here, where the JSON transport needs it ([microphone.md](microphone.md)).

The joints and audio tasks are cancelled when the client leaves, so nothing is sent after it.

### Message envelope

Every message, both directions, is `{"id": <string>, "data": <object>}`.

**Client → server:** only `id: "Command"`, with `data = {"commandUuid", "commandId", "commandData"}`. Each command runs as its own task (the server keeps a reference until it finishes), so long-running commands (e.g. `Dance`) don't block later ones (e.g. `StopDance`).

**Server → client:**

| `id` | `data` |
|---|---|
| `NaoState` | `{connected, fakeRobot}` (`fakeRobot` is true on the `fake` backend) |
| `CommandEnded` | `{commandUuid, resultType: "Success"\|"Error", message, data}` — unknown `commandId` or an exception yields `Error` |
| `Touch` | `{part, touched: bool}` |
| `Joints` | `{jointsNames, jointsAngles}` (every `streams.joints.period_s`) |
| `Audio` | `{rate, channels, nbSamplesPerChannel, data: base64 PCM16LE}`, one per mic chunk |
| `Log` | `{log, logLevel}` — server log lines mirrored to the client |

### Commands (`commandId` → `commandData` → `NaoBridge` verb)

| commandId | commandData | Result `data` |
|---|---|---|
| `GenericNao` | `{text}` | none (logs only) |
| `SetTTSLanguage` | `{language}` | — |
| `Say` / `StopSay` | `{text}` / `{}` | — |
| `WakeUp` / `Rest` / `StandUp` / `SitDown` | `{}` | — |
| `ChangeEyesColor` | `{color}` | — |
| `GetDanceBehaviors` / `GetBodyActionBehaviors` / `GetAppBehaviors` | `{}` | list of `{id, behaviorName, localizedName: {en_US, fr_FR}, description}` (camelCase) |
| `Dance` / `StopDance` | `{danceId}` | — |
| `GetExpressiveReactionTypes` | `{}` | list of strings |
| `ExpressiveReaction` / `StopExpressiveReaction` | `{reactionType}` | — |
| `BodyAction` / `StopBodyAction` | `{bodyActionId}` | — |
| `RunApp` / `StopApp` | `{appId}` | — |
| `SetBasicAwarenessState` | `{enabled, engagementMode, trackingMode}` | — |
| `SetBreathingEnabled` | `{enabled, chainName}` | — |
| `RunBehavior` / `StopBehavior` | `{name}` | — |

The `bool` result from `NaoBridge` maps to `resultType`; payloads use **camelCase** keys (unlike the MCP server's snake_case JSON).

## Open questions

1. **Bind address.** Serving on the LAN IP only (not `0.0.0.0`/localhost) and discovering it via 8.8.8.8 fails offline — make the host configurable?
2. **Protocol versioning / schema.** No version field and no published JSON schema (the README marks message docs as TODO); this table is now the reference.
3. **No auth.** Anyone on the LAN can drive the robot; acceptable for a local tool, revisit if exposed further.
