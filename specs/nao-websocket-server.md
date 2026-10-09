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

- **Config:** `NaoWebsocketServerConfig` is `{"bridge": NaoBridgeConfig, "server": WebsocketServerSettings}`, with `WebsocketServerSettings(host: str = "", port: int = 8002)` (port 0–65535; `0` lets the OS pick a free port, which `address` then reports). `host` is the address to bind; empty means the host's **LAN IP** (found via a UDP socket towards 8.8.8.8; with no route out, e.g. offline, it falls back to `127.0.0.1` with a warning, so local clients can still connect), `"0.0.0.0"` every interface, `"127.0.0.1"` local only. Both blocks are optional and share the loaders and `ConfigError` rules of [config.md](config.md). The bridge's `streams` decide which events the server streams to its client: none is forced on.
- `NaoWebsocketServer(config=None)` (default: `NaoWebsocketServerConfig()`, the fake with no streams) builds a `NaoBridge(config.bridge)`.
- **Two objects.** `NaoWebsocketServer` owns the bridge and the listener; `ClientSession` is the protocol over one connection — it takes the bridge, the config and a *connection-like* object (anything with `send(str)`, `close()` and `async for` over incoming text, which is what `websockets` gives and what a test can fake in memory) and runs `serve()` until the connection ends. The server builds one session per accepted connection. So the protocol is tested through its public surface without a network listener.
- `async start_connection()` starts the bridge. On `RobotConnectionError` it logs and returns `False`. Otherwise it listens on `server.host` (the LAN IP when empty) at `server.port`; `address` then gives the `(host, port)` actually bound. If the listener can't bind (port in use, an address that isn't this host's), it logs the error naming `host:port`, stops the bridge again and returns `False`: a `False` start leaves nothing running. The listener is the `websockets` `Server` object, held by the server and closed with it. Each accepted connection goes to `attach(connection)`, which is public: a host with its own transport can hand the server any connection-like object and get the same single-client policy.
- `async stop_connection()` ends the client's session, closes the listener, then stops the bridge.
- CLI: the `nao-websocket-server` console script (also `python -m nao_bridge.nao_websocket_server`) takes `--config path.json` only; without it the server runs on its default config. An invalid config exits 2 with the `ConfigError` message. It runs until Enter is pressed and exits 1 if the robot is unreachable. Ready-made files: `examples/configs/websocket-fake.json`, `websocket-real.json` (every stream on).

### Single client

Exactly one client at a time. A new connection ends the previous session (its streams stop, the robot is reset as on a disconnect, its connection is closed) before the new one starts; the old session's own cleanup then finds nothing left to do and logs nothing.
- On client **connect** (when the robot is connected): eyes cyan, `wake_up`, breathing on for `Body`; then a `NaoState` message is sent and the client's streams start.
- On client **disconnect**: its streams stop, then eyes white, breathing off, `rest`.
- A step of either ritual that fails is logged as a warning (and, on connect, mirrored to the client as a `Log`); the next steps still run, and the session goes on.

**Streams per client session** (each only when enabled in the bridge config):
- **Touch:** the session subscribes its handler to `bridge.on_touch` for its lifetime and sends a `Touch` message for each event.
- **Joints:** a task follows `bridge.joints.changes()` and sends a `Joints` message per published sample. It is latest-wins, so a slow connection skips poses rather than lagging.
- **Audio:** a task drains one `bridge.audio_input()` subscriber and sends an `Audio` message per chunk, base64-encoding it here, where the JSON transport needs it ([microphone.md](microphone.md)).

The joints and audio tasks are cancelled and the touch handler unsubscribed when the client leaves, so nothing is sent after it.

**Bad input doesn't end the session.** A message that isn't JSON, isn't the envelope, or has an unknown `id` is answered with a `Log` message at `ERROR` level naming the problem, and the session keeps reading. Only the connection closing (by the client or by the server) ends a session.

### Message envelope

Every message, both directions, is `{"id": <string>, "data": <object>}`.

**Client → server:** only `id: "Command"`, with `data = {"commandUuid", "commandId", "commandData"}`. Each command runs as its own task (the server keeps a reference until it finishes), so long-running commands (e.g. `Dance`) don't block later ones (e.g. `StopDance`).

**Server → client:**

| `id` | `data` |
|---|---|
| `NaoState` | `{protocolVersion, connected, fakeRobot}`: the first message of every session. `protocolVersion` is an integer (see "Protocol version"); `fakeRobot` is true on the `fake` backend |
| `CommandEnded` | `{commandUuid, resultType: "Success"\|"Error", message, data}` — always all four keys (`data` is `null` when a command has no payload); `Success` has an empty `message`. An unknown `commandId`, a `commandData` missing a field, or a failed verb yields `Error` with the reason in `message`: a bridge error's own message (`BridgeError`, `ValueError`), or `error in command '<id>': <repr>` for anything else |
| `Touch` | `{part, touched: bool}` |
| `Joints` | `{jointsNames, jointsAngles}` (every `streams.joints.period_s`) |
| `Audio` | `{rate, channels, nbSamplesPerChannel, data: base64 PCM16LE}`, one per mic chunk |
| `Log` | `{log, logLevel}` — the session's own log lines (connection, each command's start and result, bad input) mirrored to the client; the listener's and the library's logs aren't |

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

A verb that returns maps to `Success`, one that raises to `Error`; payloads use **camelCase** keys (unlike the MCP server's snake_case JSON).

### Protocol version

`NaoState.protocolVersion` is `PROTOCOL_VERSION`, a module constant, currently `1`. It is bumped on an **incompatible** change only: a message, command or field removed or renamed, or its meaning changed. Additions (a new command, a new message, a new field in an existing payload) keep the version, so a client must ignore message ids and fields it doesn't know. A client checks the version on `NaoState` and can refuse a server it wasn't written for. The tables above are the reference for the current version.

## Open questions

1. **JSON Schema.** The protocol has no machine-readable schema; the tables above are the reference. Deferred until a second client implementation (e.g. Unity/C#) needs one.
2. **No auth.** Anyone on the LAN can drive the robot; acceptable for a local tool, revisit if exposed further.
