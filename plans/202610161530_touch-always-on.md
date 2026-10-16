# Touch always on

**Status:** Done

Implements the settled behavior in `specs/config.md` ("Streams: config switches, bridge APIs"), `specs/bridge.md` ("Streams") and `specs/naoqi-websocket-server.md` ("Streams per client session"): the touch stream loses its config switch and is subscribed on every `start()`, since three `ALMemory` subscribers that fire only when a sensor changes cost nothing to keep. A touch subscription that fails is logged as a warning rather than failing `start()`. The other streams keep their switches; nothing else in the config changes.

## Scope

- `src/naoqi_bridge/config.py` — `TouchStream` and `StreamSettings.touch` removed; `streams.touch` becomes an unknown key
- `src/naoqi_bridge/__init__.py` — `TouchStream` no longer exported
- `src/naoqi_bridge/bridge.py` — `_bring_up` always subscribes touch (a failure logged as a warning, `on_touch` silent); `_teardown` always unsubscribes it
- `src/naoqi_bridge/naoqi_websocket_server.py` — the session always subscribes `bridge.on_touch`
- `examples/configs/websocket-fake.json`, `websocket-real.json`, `websocket-sim.json`, `examples/configs/README.md` — the `touch` block dropped
- `README.md` — config and streams sections without the switch
- `tests/test_config.py`, `tests/test_bridge.py`, `tests/test_naoqi_websocket_server.py` — configs without `TouchStream`; `streams.touch` rejected as unknown; the default bridge subscribes touch; a failing touch subscription is logged and the bridge still starts
- `tests-e2e/test_live_streams.py`, `tests-e2e/test_live_servers.py` — configs without `TouchStream`

## Steps

1. **Config.** Delete `TouchStream` from `config.py` (class, `StreamSettings` field, `parse` entry, `__all__`) and from the package's front door. The unknown-key check already rejects a leftover `streams.touch` with `unknown key 'streams.touch'`.
2. **Bridge.** In `_bring_up`, subscribe touch unconditionally right after the connection, inside `try/except Exception` that logs a warning (`"Touch subscription failed; on_touch will not emit"`) and continues. In `_teardown`, always add `robot.unsubscribe_touch` to the steps (both backends tolerate an unsubscribe with nothing subscribed).
3. **WebSocket server.** Drop the `streams.touch.enabled` guard around the `on_touch` subscription in `ClientSession`.
4. **Examples and README.** Remove the `touch` block from the three websocket example files and the README's two config samples; say in both READMEs that touch is always on.
5. **Tests.** Update the fast tier: the default config's streams are all off except that `streams` has no `touch`; `{"streams": {"touch": {...}}}` is an unknown-key `ConfigError`; `NaoqiBridge("fake")` records `connect` then `subscribe_touch`; a `subscribe_touch` that raises leaves the bridge running with the warning in the log and `on_touch` silent; the WebSocket session streams touch with a default bridge config. Update the two live tests that built a `TouchStream`.
6. **Statuses.** Flip `config.md`, `bridge.md` and `naoqi-websocket-server.md` from `Updated` back to `Implemented` (file and index) and this plan to `Done`.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`; the live tier's touch tests on a robot when one is at hand (`NAOQI_E2E_TARGET=real`, `touch_sensors` + `person_present`). Mark this plan `Done` (here and in [_index.md](_index.md)) only once all pass.
