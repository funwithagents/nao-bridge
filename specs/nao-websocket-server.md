---
code:
  - src/nao_bridge/nao_websocket_server.py
tests:
---

# Nao WebSocket server

**Status:** Implemented

> Retro-documented from existing code when the SDD workflow was adopted.

## Purpose

Gives non-MCP clients (a game engine, a web app, a custom agent loop) network access to [NaoAPI](nao-api.md) over a JSON WebSocket protocol — commands in, results and live robot events (touch, joints, audio, logs) out. Like the MCP server, it is an adapter with no robot logic of its own.

## Core concepts / Decided

### Lifecycle

- `NaoWebsocketServer(fake_robot, with_joints_data, with_audio_data, nao_ip, nao_port, websocket_port)`. Touch events are always wired; joints and audio streams only when their flag is set.
- `async start_connection()`: connects `NaoAPI` (returns `False` on failure), then serves on the host's **LAN IP** (found via a UDP socket towards 8.8.8.8) at `websocket_port`.
- `async stop_connection()`: disconnects `NaoAPI`, disconnects the client, closes the server.
- CLI `main()`: `--fake-robot`, `--ip`, `--port` (9559), `--websocket-port` (8002), `--with-joints-data`, `--with-audio-data`; runs until Enter is pressed.

### Single client

Exactly one client at a time. A new connection closes the previous client. On client **connect** (when the robot is connected): eyes cyan, `wake_up`, breathing on for `Body`; then a `NaoState` message is sent. On client **disconnect**: eyes white, breathing off, `rest`.

### Message envelope

Every message, both directions, is `{"id": <string>, "data": <object>}`.

**Client → server:** only `id: "Command"`, with `data = {"commandUuid", "commandId", "commandData"}`. Each command runs as its own task, so long-running commands (e.g. `Dance`) don't block later ones (e.g. `StopDance`).

**Server → client:**

| `id` | `data` |
|---|---|
| `NaoState` | `{connected, fakeRobot}` |
| `CommandEnded` | `{commandUuid, resultType: "Success"\|"Error", message, data}` — unknown `commandId` or an exception yields `Error` |
| `Touch` | `{part, touched: bool}` |
| `Joints` | `{jointsNames, jointsAngles}` (every 0.2 s) |
| `Audio` | `{rate, channels, nbSamplesPerChannel, data: base64 PCM16LE}` |
| `Log` | `{log, logLevel}` — server log lines mirrored to the client |

### Commands (`commandId` → `commandData` → `NaoAPI` call)

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

Result `bool` from `NaoAPI` maps to `resultType`; payloads use **camelCase** keys (unlike the MCP server's snake_case JSON).

## Open questions

1. **Bind address.** Serving on the LAN IP only (not `0.0.0.0`/localhost) and discovering it via 8.8.8.8 fails offline — make the host configurable?
2. **Protocol versioning / schema.** No version field and no published JSON schema (the README marks message docs as TODO); this table is now the reference.
3. **No auth.** Anyone on the LAN can drive the robot; acceptable for a local tool, revisit if exposed further.
