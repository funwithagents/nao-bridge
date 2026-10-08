# WebSocket server fixes

**Status:** Done

Implements `specs/nao-websocket-server.md` ("Single client", "Message envelope"): the three places where the server's behavior didn't match the spec. No restructuring here — that is [202610081840_websocket-server-restructure.md](202610081840_websocket-server-restructure.md).

## Scope

- `src/nao_bridge/nao_websocket_server.py` — a malformed message (not JSON, not the envelope, unknown `id`) is answered with a `Log` error and the session keeps reading; a client swap ends the previous session cleanly (robot reset, no spurious "should not happen" error); every `CommandEnded` carries all four keys, `data` being `null` when there is none.
- `tests/test_nao_websocket_server.py` — one functional test per fix.

## Steps

1. Move the per-message `try` inside the receive loop; on failure send a `Log` at `ERROR` and continue.
2. On a new connection with a client already attached, run the full disconnection for the old client (streams, robot reset, close) before attaching the new one, so the old handler's cleanup finds nothing to do.
3. Add `"data": None` to the unknown-command answer.
4. Tests: a session that receives garbage then a valid command answers the command; a second client makes the first one's `rest` run and logs no error; the unknown-command answer has `data`.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` clean.
