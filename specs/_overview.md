# naoqi-bridge — Overview

naoqi-bridge connects AI agents and applications to Aldebaran's Nao robot, and in principle to any robot running Naoqi. One async Python object, `NaoqiBridge`, hides the Naoqi `qi` session and its services behind intent-level verbs (speak, stand up, dance, react, run an installed app) and streams the robot's touch, joint and microphone data back out. Two thin adapters expose that one object without duplicating its logic: an MCP server for LLM agents and a JSON WebSocket server for custom applications. Under the bridge, a robot seam has two implementations, a Naoqi over `qi` and an offline fake, behind three backends: a real Nao, a simulated one the bridge can start itself (naoqi-sim, in Docker), and the fake, so the whole stack runs and is tested with no hardware, and the fast tests with no `qi` wheel.

This overview is the map of the project: what it is for, how the parts fit, the rules that cut across them, and where each part stands. Each concept has its own spec (see [_index.md](_index.md)), which is the authority on its details; the sections here summarize and link. It is reference material without a status.

## Goals

- An agent or application drives a Nao with **intent-level verbs**, not Naoqi service calls: it says what the robot should do and learns why it couldn't.
- **One implementation, every client.** A Python caller, an MCP client (Claude Desktop, Tiny Agents) and a WebSocket client (a game engine, a web app) all reach the same `NaoqiBridge`, so a behavior fixed once is fixed for all.
- **Runs without a robot.** The `fake` backend is the default; the library, both servers and the whole fast test tier run offline, on any platform, with no `qi` wheel.
- **Never pretends.** A `real` backend that can't reach the robot, or a platform with no `qi`, fails loudly; the bridge never falls back to the fake on its own.
- **Reproducible setups.** Which robot and which streams is one JSON file, checked when it loads; switching from the robot to the fake is a one-word change.

## Scope

| In scope | Out of scope |
| --- | --- |
| Intent-level verbs over Naoqi: speech, motors and postures, eyes, breathing, basic awareness, installed behaviors | Exposing Naoqi's full API; a raw service escape hatch beyond `bridge.robot` |
| A catalog of what's installed (dances, expressive reactions, body actions, apps), classified from the robot's package list | Installing or managing packages on the robot |
| Robot streams: touch events, joint angles, microphone audio | Camera images, perception, speech recognition (open questions below) |
| An MCP server and a WebSocket server over the bridge | Authentication, multi-client arbitration (the WebSocket server takes one client at a time) |
| `real` (Naoqi over `qi`), `sim` (naoqi-sim, started or borrowed) and `fake` (offline) backends | Simulating Naoqi itself: naoqi-sim does, the bridge only starts, borrows and stops it |
| Naoqi 2.1.4.13 on Nao v5, the only verified target | Nao v6, Pepper and newer Naoqi: expected to need adjustments inside `RealNaoqiRobot` only ([robot.md](robot.md)) |

## Architecture

```
  LLM agent (MCP client)         custom app (WebSocket client)          Python caller
          │ stdio / SSE                    │ JSON over WebSocket              │
  ┌───────▼────────┐             ┌─────────▼────────────┐                     │
  │ NaoqiMcpServer │             │ NaoqiWebsocketServer │                     │
  │    (tools)     │             │   + ClientSession    │                     │
  └───────┬────────┘             └─────────┬────────────┘                     │
          └──────────────────┬─────────────┴──────────────────────────────────┘
                     ┌───────▼────────┐   built from NaoqiBridgeConfig
                     │  NaoqiBridge   │   verbs · catalog · on_touch · joints · mic
                     └──┬─────────┬───┘
     sim backend:       │         │ NaoqiRobot Protocol (blocking calls, run off the loop)
     start or borrow ┌──▼──────┐  └───────┬──────────────────┬──────────────────┐
     the sim first   │ sim.py  │  ┌───────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
                     │ (lease) │  │ RealNaoqiRobot │ │ SimNaoqiRobot  │ │ FakeNaoqiRobot │
                     └──┬──────┘  │   qi session   │ │ (a Real one)   │ │   in-process   │
                        │         └───────┬────────┘ └───────┬────────┘ └────────────────┘
                        │ NaoqiSim        │ tcp://<ip>:9559  │ tcp://127.0.0.1:9559
                        └──────────▶ Naoqi: a Nao, or naoqi-sim's NAOqi in Docker
```

| Part | Module | Role | Spec |
| --- | --- | --- | --- |
| Config | `config.py` | `NaoqiBridgeConfig` (backend, robot, streams, sim), the `from_dict` / `from_json` / `from_json_file` loaders, `ConfigError` naming the key | [config.md](config.md) |
| Robot seam | `robot.py` | The `NaoqiRobot` Protocol (the exact Naoqi slice the bridge consumes), shared constants and types, `RobotConnectionError`, `build_robot(config)` | [robot.md](robot.md) |
| Real backend | `real_robot.py` | `RealNaoqiRobot`: each Protocol method as Naoqi service calls over a `qi` session, imported lazily; bounded connection attempts | [robot.md](robot.md) |
| Sim | `sim.py` | The `sim` backend's lease: start a naoqi-sim and own it, or borrow the one running, as `sim.spawn` says; the one module that imports `naoqi_sim` | [sim.md](sim.md) |
| Sim robot | `sim_robot.py` | `SimNaoqiRobot`: `RealNaoqiRobot` at naoqi-sim's address; Sit through Crouch on NAOqi 2.8 | [robot.md](robot.md), [sim.md](sim.md) |
| Fake backend | `fake_robot.py` | `FakeNaoqiRobot`: records commands, serves a fixed package list, behaviors that take time, motors that start off, sensor events and paced audio | [robot.md](robot.md) |
| Bridge | `bridge.py`, `errors.py` | `NaoqiBridge`: lifecycle, verbs that raise why they failed, behavior catalog, running-item tracking, stream APIs | [bridge.md](bridge.md) |
| Event | `events.py` | `Event[T]`: synchronous pub/sub, for occurrences (`bridge.on_touch`) | [events.md](events.md) |
| Observable | `observable.py` | `Observable[T]`: readable and subscribable latest-wins state (`bridge.joints`) | [observable.md](observable.md) |
| Mic feed | `microphone.py` | `MicFeed`: one subscription to Naoqi's pushed audio, a 200-chunk ring, any number of `audio_input()` subscribers | [microphone.md](microphone.md) |
| MCP server | `naoqi_mcp_server.py` | `NaoqiMcpServer`: verbs as MCP tools returning status strings; behaviors return once started; stdout reserved for JSON-RPC | [naoqi-mcp-server.md](naoqi-mcp-server.md) |
| Viewer | `viewer.py` | A naoqi-viewer mirror window on the robot the bridge drives, opened with the session; the one module that launches naoqi-viewer | [viewer.md](viewer.md) |
| WebSocket server | `naoqi_websocket_server.py` | `NaoqiWebsocketServer` (bridge + listener, one client at a time) and `ClientSession` (the JSON protocol: commands in, touch / joints / audio / log events out) | [naoqi-websocket-server.md](naoqi-websocket-server.md) |
| Front door | `__init__.py` | Re-exports what a caller needs: `NaoqiBridge`, the config classes, the stream values, `Event` / `Observable`, the errors | [bridge.md](bridge.md) |

Dependencies point one way: servers → bridge → seam → backends. `events.py` and `observable.py` import nothing from the project; `config.py` imports neither `qi`, `mcp` nor `websockets`; only `real_robot.py` touches `qi`, and only when it connects; only `sim.py` starts naoqi-sim and only `viewer.py` launches naoqi-viewer, and `config.py` reads their config classes, all lazily.

## Status

Every spec is `Implemented`, and every plan in [plans/_index.md](../plans/_index.md) is `Done`.

| Concept | State |
| --- | --- |
| Config and server configs, `--config` CLIs, example files | Built and tested ([config.md](config.md)) |
| Robot seam, `real` and `fake` backends | Built and tested; `real` verified live on Naoqi 2.1.4.13 / Nao v5 only ([robot.md](robot.md)) |
| `NaoqiBridge`: verbs, catalog, errors, streams, cancellation | Built and tested ([bridge.md](bridge.md)) |
| `Event`, `Observable`, mic feed | Built and tested ([events.md](events.md), [observable.md](observable.md), [microphone.md](microphone.md)) |
| MCP server | Built and tested ([naoqi-mcp-server.md](naoqi-mcp-server.md)) |
| WebSocket server, protocol version 1 | Built and tested ([naoqi-websocket-server.md](naoqi-websocket-server.md)) |
| Viewer (naoqi-viewer mirror window, `[viewer]` extra) | Built and tested; the live check (`NAOQI_E2E_VIEWER=1`) passes locally on a 2.1 sim, as `real` and as a borrowed `sim`; not in CI, which has no display ([viewer.md](viewer.md)) |
| Project tooling, two test tiers, CI | In place ([project.md](project.md), [testing.md](testing.md), [ci.md](ci.md)) |
| Live tier | Verbs, streams, cancellation and both servers, each test gated on the capabilities it needs ([testing_support.md](testing_support.md)); passes on 2.1 and 2.8 sims, in CI (and locally before the capabilities) (`e2e-sim`); not yet run on a robot ([analysis](../analysis/202610091738_not-yet-tested-on-a-robot.md)) |
| `sim` backend, live tier on a sim, `e2e-sim` CI job | Built and tested; the live tier passes on 2.1 and 2.8 sims, locally and in CI ([sim.md](sim.md), [ci.md](ci.md)) |

## How a call flows

- **Verbs.** Every verb is `async`. The bridge checks it's running (`NotRunningError`), resolves catalog ids (`ValueError` naming the known ones), asks the robot whether the motors are on when the verb moves the body (`MotorsOffError`), then runs the blocking robot call in `asyncio.to_thread`. A Naoqi exception comes back as `CommandFailedError`, chained. Success returns `None`. Cancelling the awaiting task interrupts any verb. A spanning verb (`say`, the postures, behaviors and the catalog verbs) sends its stop and waits for the robot call to return before re-raising, so the robot has stopped by the time the caller sees the `CancelledError` ([bridge.md](bridge.md) "Cancellation"). So `except (BridgeError, ValueError)` catches every expected failure, and both servers turn exactly those into a readable reason for their client ([bridge.md](bridge.md) "Errors").
- **Long-running behaviors.** On the bridge, `dance`, `expressive_reaction`, `body_action`, `run_app` and `run_behavior` await the behavior's end, and the item shows in `current_*` while it runs; the stop verbs are called concurrently. The servers don't hold their client for minutes: the WebSocket server runs each command as its own task, and the MCP tools return once the item is seen playing ([naoqi-mcp-server.md](naoqi-mcp-server.md)).
- **Streams.** Naoqi calls back on its own threads. The bridge marshals touch onto its event loop and re-emits it on `on_touch`; a bridge task samples joints every `period_s` into `joints`; the mic feed writes each pushed buffer into its ring under a lock and wakes its subscribers through `call_soon_threadsafe`. Consumers only ever see the event loop.

## Cross-cutting rules

- **Three stream shapes, chosen by what the data is.** An occurrence where every one matters and nothing replays is an `Event` (touch). A state where only the latest matters is an `Observable` (joints). A continuous signal every consumer needs whole, at its own pace, is a ring with cursors (audio). Each shape has any number of consumers; none is a callback.
- **The config switches streams; the bridge's APIs consume them.** A stream is subscribed on the robot at `start()` only when the config enables it, and using a disabled stream's API raises `BridgeError` ([config.md](config.md)).
- **Every verb is cancellable.** Cancelling the task is the one way to interrupt a verb: the effect it started stops, the cancel returns in bounded time, and the session stays usable. There's no rewind ([bridge.md](bridge.md) "Cancellation").
- **Raise why, not whether.** No verb returns `bool`; each failure has a type and a message an agent can act on.
- **The Protocol is the contract.** pyright checks both backends against `NaoqiRobot`, so the fake can't drift from what the bridge calls. Units and names at the seam are Naoqi's; intent belongs to the bridge.
- **Fake is the default and honest.** `NaoqiBridgeConfig()` is the fake; a real robot always means an explicit config with `robot.ip`. The fake behaves like a robot where tests and demos need it (motors start off, behaviors last 5 s, speech 1 s and posture moves 2 s, all stoppable, audio is pushed at Naoqi's pace).
- **Adapters hold no robot logic.** Each server maps its protocol onto bridge verbs and back; logic found in a server belongs in the bridge.
- **The library never configures the process.** Modules log through `logging.getLogger(__name__)`; logging setup, stdout handling and exit codes belong to the CLIs.

## Configuration

One JSON shape, `NaoqiBridgeConfig`: `backend` (`fake` by default, `real` or `sim`), `robot` (`ip`, `port`, `connect_timeout_s`), `streams` (`touch`, `joints`, `audio`, all off by default) and `sim` (`spawn`: `auto` by default, `never` or `always`; `config`: a naoqi-sim config as it is) and `viewer` (`enabled`; `config`: a naoqi-viewer config, minus what the bridge sets). Unknown keys, bad types and a `real` backend without an IP fail at load with a `ConfigError` naming the key path. Each server wraps it as `{"bridge": …, "server": …}`, and its CLI takes `--config FILE` only (exit 2 on a bad config, 1 on an unreachable robot or an unavailable sim). Ready-made files live in `examples/configs/`. Details: [config.md](config.md).

## Packaging and platforms

- Python 3.12–3.13, packaged with uv, `src/` layout; runtime dependencies `mcp<2`, `websockets` and, where a wheel exists, `qi>=3.1.8,<4` ([project.md](project.md)).
- `qi` comes from the package index of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork on GitHub Pages, `https://funwithagents.github.io/libqi-python/simple/`; PyPI only has the older 3.1.5. uv reads it from `pyproject.toml`; pip needs `--extra-index-url` with that URL.

  | Platform | `qi` | Backends |
  | --- | --- | --- |
  | macOS arm64, Linux x86_64, Windows x64 (CPython 3.12 / 3.13) | installed by `uv sync` | `real` and `fake` |
  | macOS x86_64, Linux aarch64, Windows arm64 | absent | `fake` only |

- `naoqi_bridge` imports everywhere, since `qi` is imported only when `RealNaoqiRobot` connects. That connection makes one attempt bounded by `connect_timeout_s`, which a cancelled `start()` gives up in flight ([robot.md](robot.md)).
- Console scripts: `naoqi-mcp-server`, `naoqi-websocket-server`.

## Testing and CI

- Two tiers, split by directory ([testing.md](testing.md)): `tests/`, fast and deterministic, runs the bridge and both servers on `FakeNaoqiRobot`, and `RealNaoqiRobot` / `SimNaoqiRobot` against a stub `qi`; `tests-e2e/`, opt-in, runs against a headless naoqi-sim by default (one per session, owned by the harness's `live_target` fixture, which gives tests the `NaoqiSim`; `NAOQI_E2E_SIM_VERSION`, `NAOQI_E2E_SIM_VIEWER=1` for the window; skips without Docker or the images unless `NAOQI_E2E_TARGET=sim` is set) or a real Nao (`NAOQI_E2E_TARGET=real`, `NAOQI_E2E_IP`). Its tests gate on **capabilities**, never on the target: probed from the target (`dances`, `audio_inject`, `touch_sensors`, …) or declared by the person running the tests (`room_to_move` from `NAOQI_E2E_ALLOW_MOTION`, always held on a sim; `person_present` from `NAOQI_E2E_INTERACTIVE`; `display` from `NAOQI_E2E_VIEWER`), through `@pytest.mark.requires(...)`. A profile names what a kind of target must offer (`sim`, the default on a sim; `nao`), and a capability it names that's missing fails the run. The harness ships as `naoqi_bridge.testing` ([testing_support.md](testing_support.md)). It prints what it measured, such as cancel latencies and the audio chunk size.
- The fast tier makes fake behaviors instant through an autouse fixture; a test that needs a running behavior sets its duration on the fake.
- CI ([ci.md](ci.md)) runs `check` (ruff lint and format, pyright) on `ubuntu-24.04` and `fast-tier` on `ubuntu-24.04`, `macos-15` and `windows-2025`, for every pull request and push to `main`. Each runner installs its real `qi` wheel, so the `qi`-gated tests run on all three. `e2e-sim` runs the live tier on a headless sim, once per NAOqi version (2.1, 2.8), with the sim images built and cached by the runner.
- `tests/test_project_map.py` keeps [AGENTS.md](../AGENTS.md)'s project map and the specs' frontmatter honest.

## Open questions

Collected from the concept specs, which own them.

- **The sim** ([sim.md](sim.md)): touch on a sim waits for naoqi-sim's touch input; dances, apps and body actions for packages a sim can install; several sims per machine for naoqi-sim's configurable ports.
- **Newer robots** ([robot.md](robot.md)): only Naoqi 2.1.4.13 / Nao v5 is verified. Nao v6 (Naoqi 2.8) or Pepper may need different service calls inside `RealNaoqiRobot`; the Protocol shouldn't change.
- **Cancellation** ([bridge.md](bridge.md)): whether the newest `say` should interrupt the one in flight; checking live that `stopAll` also stops animated speech's gestures.
- **Microphone** ([microphone.md](microphone.md)): Naoqi's real chunk size at 16 kHz mono is unmeasured (the fake's 1360 samples is a placeholder); 48 kHz four-channel capture and a gap signal in the stream are deferred.
- **The viewer** ([viewer.md](viewer.md)): mirroring the fake (needs a naoqi-viewer pose source fed by the bridge), reopening a closed window, a second window on a borrowed sim that shows its own.
- **Config blocks** ([config.md](config.md)): motion, session state (what the robot does at start and stop) and catalog rules are candidate blocks, added when needed.
- **WebSocket protocol** ([naoqi-websocket-server.md](naoqi-websocket-server.md)): no machine-readable schema, no authentication.
- **Publishing on PyPI** ([project.md](project.md)): naoqi-bridge installs from its repository; a published wheel would resolve `qi` through the libqi index. Undecided.
- **Live-tier capabilities** ([testing_support.md](testing_support.md)): `touch_inject`, `inertial` and the robot model join the vocabulary with the first test that needs them (`inertial` could also replace the 2.8 sim's Sit-through-Crouch rule); consumer-defined profiles and a `fake` target for consumers' smoke runs are deferred.
- **CI coverage** ([ci.md](ci.md)): a Python 3.13 entry, deferred until a regression shows the need.
- **Not yet designed:** camera images, perception (faces, people), speech recognition, and how they'd reach agents. None has a spec.
