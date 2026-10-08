# WebSocket server restructure

**Status:** Done

Implements `specs/nao-websocket-server.md` ("Lifecycle": the `ClientSession` / listener split and `server.host`) and `specs/config.md` (`WebsocketServerSettings(host, port)`). Builds on [202610081830_websocket-server-fixes.md](202610081830_websocket-server-fixes.md). The wire protocol is unchanged.

## Scope

- `src/nao_bridge/nao_websocket_server.py`:
  - `ClientSession(bridge, config, connection)` — the protocol over one connection-like object (`send`, `close`, `async for`): `NaoState`, robot init/reset, the per-session touch/joints/audio streams, command dispatch, `Log` mirroring of its own lines. `serve()` runs until the connection ends.
  - `NaoWebsocketServer` — the bridge, the listener (holds the `websockets` `Server`; `address` is what it bound), one session at a time; no copies of config or bridge state.
  - Commands as a table: `commandId` → (argument extractor, bridge verb); one serializer for the three catalog getters.
  - Fully typed (`ServerConnection` where a real connection is required, a small `Connection` Protocol for the session); log messages formatted, not concatenated.
  - `WebsocketServerSettings.host` (default `""` = LAN IP).
- `tests/test_nao_websocket_server.py` — drives `ClientSession` with an in-memory connection and `NaoWebsocketServer` through `start_connection` / `stop_connection` on `127.0.0.1` with an ephemeral port; no private calls.
- `tests/test_config.py` — `host` loads and defaults.
- `README.md`, `examples/configs/websocket-*.json` — `host` documented (examples keep the default).

## Steps

1. Add `host` to `WebsocketServerSettings`; LAN IP discovery only when empty.
2. Extract `ClientSession`; port the fixes from the previous plan into it; replace the 25 handlers with the table.
3. Rewrite the listener on the `Server` object; drop the events and the duplicated state.
4. Rewrite the tests on the public surface; add a real-socket test with `websockets.connect` to a `127.0.0.1:0` listener.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` clean.
