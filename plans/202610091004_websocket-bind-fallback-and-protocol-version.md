# WebSocket bind fallback and protocol version

**Status:** Done

Implements the settled behavior in `specs/nao-websocket-server.md` ("Lifecycle", "Message envelope", "Protocol version"), closing the analysis's C3 and C4.

- **C3:** the `server.host` field and the fast-tier test that serves a real client on `127.0.0.1` already exist (plan `202610081840`). What's left is the start path: offline, an empty `host` now falls back to `127.0.0.1` instead of raising, and a listener that can't bind stops the bridge again, so `start_connection()` never leaves anything running.
- **C4:** `NaoState` carries `protocolVersion` (an integer, `1`), with a rule for when it changes.

It leaves out a JSON Schema for the protocol (deferred until a second client implementation needs it) and authentication (C5).

## Design

- **LAN IP fallback.** `_lan_ip()` catches the `OSError` of the UDP probe (no route out), logs a warning ("no route out; listening on 127.0.0.1 only") and returns `"127.0.0.1"`.
- **Failed bind.** In `start_connection()`, an `OSError` from `websockets.serve` (port in use, an address that isn't this host's) is logged as an error naming `host:port`, the bridge is stopped, and the method returns `False`, as it does for an unreachable robot. The CLI already exits 1 on `False`.
- **Protocol version.** A module constant `PROTOCOL_VERSION = 1`, sent as `NaoState.protocolVersion`. It is bumped on an **incompatible** change only: a message, command or field removed or renamed, or its meaning changed. Additions (a new command, a new message, a new field in an existing payload) keep the version, and clients ignore what they don't know. Clients read it from the first message of every session.

## Scope

- `specs/nao-websocket-server.md`: the fallback and the failed bind in "Lifecycle", `protocolVersion` in the `NaoState` row, a "Protocol version" section with the rule, open question 1 narrowed to the deferred JSON Schema (its stale "README marks message docs as TODO" dropped). `Updated` while this plan is open, back to `Implemented` at the end.
- `specs/config.md`: one clause for the fallback where it describes `host` (editorial, status kept).
- `src/nao_bridge/nao_websocket_server.py`: `_lan_ip()` fallback, `start_connection()` bind failure, `PROTOCOL_VERSION` in `NaoState`.
- `tests/test_nao_websocket_server.py`: `NaoState` assertions with `protocolVersion`; with no route out (the module's `socket` replaced by a stub whose `connect` raises), an empty host listens on `127.0.0.1` and logs the warning; a port already bound makes `start_connection()` return `False` with the bridge stopped.
- `README.md`: the fallback in the `server` block sentence; `protocolVersion` next to the pointer to the protocol spec.
- `analysis/202610080900_robot-bridge-open-questions.md`: C3 and C4 removed, prune line updated.

## Steps

1. Specs edited, the WebSocket spec `Updated` (file and index).
2. Server: fallback, bind failure, protocol version.
3. Tests, README, analysis.
4. Verify, then this plan `Done` and the spec back to `Implemented`.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean. Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
