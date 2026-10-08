# Config and stream APIs

**Status:** Done

Implements `specs/config.md` and `specs/microphone.md` (both `Stable`), the new `specs/events.md` and `specs/observable.md`, and the edits they bring to `specs/bridge.md`, `specs/robot.md`, `specs/nao-mcp-server.md` and `specs/nao-websocket-server.md` (all `Updated`). It delivers:
- `NaoBridgeConfig` with its loaders and `ConfigError`;
- the server configs (`{"bridge", "server"}`) and the `--config`-only CLIs;
- the stream APIs replacing callbacks: touch `Event`, joints `Observable`, and the mic feed with `audio_input()` subscribers;
- the fake's paced audio, and example config files.

It leaves out every spec's open questions: the joints API alternative, multichannel audio, strict continuity, measuring Naoqi's chunk size, and the deferred config blocks (motion, session state, catalog rules, `sim`).

## Scope

- `src/nao_bridge/errors.py` — **new**: `BridgeError` moves here from `bridge.py`, so `microphone.py` can raise it without importing the bridge.
- `src/nao_bridge/config.py` — **new**:
  - `Backend`, `AudioChannel`, `ConfigError`;
  - `RobotSettings`, `TouchStream` / `JointsStream` / `AudioStream`, `StreamSettings`, `NaoBridgeConfig` (frozen dataclasses);
  - the `from_dict` / `from_json` / `from_json_file` trio, and the field readers server configs reuse.
- `src/nao_bridge/events.py` — **new**: `Event[T]`.
- `src/nao_bridge/observable.py` — **new**: `Observable[T]`.
- `src/nao_bridge/microphone.py` — **new**: `MicChunk`, `MicFeed`, `MIC_RING_CHUNKS`.
- `src/nao_bridge/robot.py`:
  - `build_robot(config)`;
  - `QiNaoRobot(ip, port, connect_tries)`;
  - `subscribe_audio(callback, channel)` with the Naoqi channel codes;
  - `FakeNaoRobot`'s paced silent push (`audio_chunk_s`).
- `src/nao_bridge/bridge.py`:
  - `NaoBridge(config | backend)` with the loader classmethods and `config`;
  - `on_touch`, `joints`, `mic`, `audio_input()`;
  - callbacks removed;
  - `TouchEvent` and `JointsState`.
- `src/nao_bridge/__init__.py` — front-door exports.
- `src/nao_bridge/nao_mcp_server.py` — `McpServerSettings`, `NaoMcpServerConfig`, `NaoMcpServer(config)`, `--config`.
- `src/nao_bridge/nao_websocket_server.py` — `WebsocketServerSettings`, `NaoWebsocketServerConfig`, `NaoWebsocketServer(config)`, `--config`; touch handler; per-client joints and audio stream tasks.
- `examples/configs/` — **new**: `mcp-fake.json`, `mcp-real.json`, `websocket-fake.json`, `websocket-real.json`.
- Tests:
  - **new**: `tests/test_config.py`, `tests/test_events.py`, `tests/test_observable.py`, `tests/test_microphone.py`;
  - updated: `tests/test_robot.py`, `tests/test_bridge.py`, `tests/test_nao_mcp_server.py`, `tests/test_nao_websocket_server.py`, `tests-e2e/test_real_robot.py`.
- Docs:
  - `specs/*` (frontmatter and statuses), `specs/_index.md`;
  - `AGENTS.md` project map (5 new modules);
  - `README.md` (configs, stream APIs, `--config` launch).

## Steps

1. **Specs.**
   - `config.md` and `microphone.md` → `Stable`.
   - Write `events.md` and `observable.md` (`Stable`).
   - Edit `bridge.md`, `robot.md` and both server specs to the new design → `Updated`.
2. **`errors.py`, `events.py`, `observable.py`.** Standalone, standard library only. `observable.py` only depends on `asyncio`.
3. **`config.py`.**
   - Each class validates its own ranges in `__post_init__`, with messages that start with the field name. `from_dict` checks the object shape, unknown keys and types with full key paths, and prefixes nested errors with their path.
   - `NaoBridgeConfig.__post_init__` enforces `real` ⇒ `robot.ip`.
   - The JSON loaders are shared through a `JsonConfig` base class.
4. **Robot seam.**
   - `build_robot(config)`; `QiNaoRobot` gets `connect_tries`.
   - `subscribe_audio(callback, channel)` maps `front` / `rear` / `left` / `right` to 3 / 4 / 1 / 2.
   - The fake starts a push thread on `subscribe_audio`. It sends a silent `audio_chunk_s × 16000`-sample chunk every `audio_chunk_s` (default 0.085 s), skipping turns while `audio_chunk_s` is `None`, and stops on `unsubscribe_audio` / `close`.
5. **`microphone.py`** per the spec: the push is the publish (under the lock, dropped when not running); the ring, cursors, lap warning, `preroll_s`, session end and `latest()`.
6. **Bridge.**
   - `start()` connects, subscribes touch (its forwarder emits `TouchEvent` on the loop through `call_soon_threadsafe`), starts the mic feed when audio is enabled, loads the catalog, and starts the joints task (`joints.set(JointsState(...))` every `period_s`).
   - `stop()` reverses that, publishes `None` on `joints`, and stops the feed before closing the robot.
   - `joints` / `audio_input()` raise `BridgeError` when their stream is disabled; `audio_input()` also raises when the bridge isn't running.
7. **Servers.**
   - Config classes and `--config` (a `ConfigError` exits 2 through `parser.error`).
   - WebSocket server: touch handler → `Touch` message; per client session, a joints follower → `Joints` and an audio subscriber → `Audio` (base64 of the chunk, rate and channels from `bridge.mic`). Both are cancelled on disconnection.
8. **Tests:**
   - config: valid files and every error path;
   - `Event` and `Observable` semantics;
   - the mic feed on the fake: two subscribers both get every chunk, lapping, pre-roll, cancellation, session end, `latest()`;
   - the bridge streams;
   - both servers on example configs;
   - the WebSocket server's `Touch` / `Joints` / `Audio` messages.
9. **Docs, examples, statuses.** All specs → `Implemented`, this plan → `Done`.

## Verification

Done 2026-10-08:
- `ruff check` and `ruff format --check` are clean; `pyright` reports 0 errors.
- `pytest` passes 98 tests, and the stream tests (mic feed, bridge, WebSocket, observable) passed 8 repeated runs. `tests-e2e` skips without `qi`.
- Both CLIs serve on their `fake` example configs (and with no config). The `real` ones exit 1 with the `qi` hint. A bad config exits 2 naming `bridge.streams.joints.period_s`.
- A real WebSocket client against `websocket-fake.json` received `NaoState`, `Touch`, `Joints`, `Audio` and `CommandEnded`.
- During implementation, `ruff` was found to format Markdown code fences, so `specs/` and `plans/` were excluded from it (`specs/project.md`).

The original checklist:

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean, with the stream tests rerun a few times to check their timing holds. `uv run pytest tests-e2e` skips cleanly without `qi`. Both CLIs start on each example config (`fake` ones fully; `real` ones fail with exit 1 and the `qi` hint), and a bad config exits 2 naming the key.
