# libqi from its package index, Windows, connect in one attempt

**Status:** Done

Implements [project.md](../specs/project.md) ("`qi` is a platform dependency", "Windows"), [robot.md](../specs/robot.md) (`RealNaoRobot`'s one cancellable connect), [config.md](../specs/config.md) (`robot.connect_tries` gone), [bridge.md](../specs/bridge.md) (Lifecycle: a cancelled `start()` gives up the connection; catalog stop verbs confirm the stop), [naoqi-websocket-server.md](../specs/naoqi-websocket-server.md) (a session closed while opening) and [ci.md](../specs/ci.md) (the fast tier on three platforms). `qi>=3.1.8,<4` comes from the libqi fork's package index on GitHub Pages instead of per-wheel release URLs, Windows x64 gets the real backend beside macOS arm64 and Linux x86_64, and the connection retry goes, since libqi 3.1.8 fixed the failed connects it was there for. Other platforms still install and run the fake backend only. A live CI job against a simulated Nao stays out of scope (ci.md open question 1).

## Scope

- `pyproject.toml`: `qi>=3.1.8,<4` with Windows x64 in its marker; the `libqi` index (`explicit = true`) and `qi = { index = "libqi" }`; the five `environments` kept
- `uv.lock`: relocked (qi 3.1.8 from the index, six wheels)
- `.gitattributes`: every text file checked out with LF
- `src/naoqi_bridge/real_robot.py`: `connect(cancel=None)` in one attempt bounded by `connect_timeout_s`, polled every `CONNECT_POLL_S` (50 ms) for the cancel; `connect_tries` gone; the missing-`qi` message names Windows x64
- `src/naoqi_bridge/robot.py`: `NaoRobot.connect(cancel=None)`; `build_robot` without `connect_tries`
- `src/naoqi_bridge/fake_robot.py`: `connect(cancel=None)` refuses an already-set cancel
- `src/naoqi_bridge/bridge.py`: `start()` hands `connect` a `threading.Event` and sets it on a cancel
- `src/naoqi_bridge/config.py`: `RobotSettings.connect_tries` removed
- `src/naoqi_bridge/bridge.py` (from CI's Windows run): a catalog stop verb re-sends `stop_behavior` until the behavior's run returns, as a cancel does
- `src/naoqi_bridge/naoqi_websocket_server.py` (from CI's Windows run): a session closed during its connect ritual subscribes nothing and unsubscribes only what it subscribed
- `tests/test_real_robot.py`: a failed connect is not retried; a silent host fails at the timeout; a cancel gives up the attempt in flight; an already-set cancel makes no attempt (in place of the two retry tests)
- `tests/test_bridge.py`: a cancelled `start()` gives up a pending connection; a `stop_dance` landing before Naoqi starts the dance still stops it
- `tests/test_naoqi_websocket_server.py`: a session closed while opening streams nothing
- `tests/test_config.py`, `tests/test_robot.py`, `tests/test_naoqi_mcp_server.py`, `tests/test_naoqi_websocket_server.py`: without `connect_tries`; `connect_tries` is an unknown key
- `tests-e2e/support.py`, `tests-e2e/test_live_servers.py`, `tests-e2e/test_live_cancellation.py`: without `connect_tries`; the mid-connection cancel bound is under 1 s instead of the attempt's timeout
- `examples/configs/*-real.json`: without `connect_tries`
- `.github/workflows/ci.yml`: `fast-tier` as a matrix over `ubuntu-24.04`, `macos-15`, `windows-2025`
- `README.md`, the specs above, `specs/_overview.md`, `specs/_index.md`, this plan, `plans/_index.md`

## Steps

1. Switch `qi` to the index, add Windows x64 to its marker, relock; check that pip installs naoqi-bridge with `qi` 3.1.8 given `--extra-index-url`.
2. One connect attempt in `RealNaoRobot`, with the cancel event through the seam and the bridge; remove `connect_tries` from the config, the backend, the examples and the tests.
3. `.gitattributes`; the fast-tier matrix.
4. Specs, README, overview, indexes.
5. Fix what the first CI runs show. [Run 38390019808](https://github.com/funwithagents/naoqi-bridge/actions/runs/38390019808): Linux and macOS green; on Windows the MCP server's stdout guard held against libqi's real log, and 2 tests failed on races Windows' slower thread start-up exposed, both bridge bugs: a `stop_dance` landing before the behavior started was lost (the dance played on), and a WebSocket session closed during its connect ritual unsubscribed a touch handler it hadn't subscribed yet (and would have subscribed it after the close). Each now has a test that reproduces it on macOS by slowing the fake, and fails without its fix.
6. Statuses, once a run on GitHub is green: this plan `Done`; project.md, robot.md, config.md, bridge.md, naoqi-websocket-server.md and ci.md `Implemented`.

## Verification

- Locally on macOS arm64 with qi 3.1.8: lint, format, types, the fast tier (171 passed). With the real wheel, `RealNaoRobot` fails at once on a refused port and after `connect_timeout_s` on a silent host, and the live tier's mid-connection cancel of `start()` returned in 21 ms (it used to wait out the attempt).
- Step 1 measured with uv 0.11.29 and pip (CPython 3.12, fresh venv): the lock holds `qi` 3.1.8 from the index with its macOS arm64, manylinux x86_64 and Windows amd64 wheels for cp312 and cp313; pip installed naoqi-bridge with `qi` 3.1.8.
- On GitHub: every job green on [run 38390475017](https://github.com/funwithagents/naoqi-bridge/actions/runs/38390475017), the fast tier 171 passed with no skip on Linux, macOS and Windows (the `qi`-gated tests included).
