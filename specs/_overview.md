# Nao Bridge — Overview

Nao Bridge connects AI agents and applications to Aldebaran's Nao robot, and in principle to any robot running Naoqi. One async Python object, `NaoBridge`, hides the Naoqi `qi` session and its services behind intent-level verbs (speak, stand up, dance, react, run an installed app) and streams the robot's touch, joint and microphone data back out. Two thin adapters expose that one object without duplicating its logic: an MCP server for LLM agents and a JSON WebSocket server for custom applications. Under the bridge, a robot seam has two backends, a real Nao over `qi` and an offline fake, so the whole stack runs and is tested with no hardware and no `qi` wheel.

This overview is the map of the project: what it is for, how the parts fit, the rules that cut across them, and where each part stands. Each concept has its own spec (see [_index.md](_index.md)), which is the authority on its details; the sections here summarize and link. It is reference material without a status.

## Goals

- An agent or application drives a Nao with **intent-level verbs**, not Naoqi service calls: it says what the robot should do and learns why it couldn't.
- **One implementation, every client.** A Python caller, an MCP client (Claude Desktop, Tiny Agents) and a WebSocket client (a game engine, a web app) all reach the same `NaoBridge`, so a behavior fixed once is fixed for all.
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
| `real` (Naoqi over `qi`) and `fake` (offline) backends | Simulating Naoqi itself; a simulated Naoqi is reached as `real` at its address |
| Naoqi 2.1.4.13 on Nao v5, the only verified target | Nao v6, Pepper and newer Naoqi: expected to need adjustments inside `RealNaoRobot` only ([robot.md](robot.md)) |

## Architecture

```
  LLM agent (MCP client)         custom app (WebSocket client)        Python caller
          │ stdio / SSE                    │ JSON over WebSocket            │
  ┌───────▼────────┐             ┌─────────▼──────────┐                     │
  │  NaoMcpServer  │             │ NaoWebsocketServer │                     │
  │   (tools)      │             │  + ClientSession   │                     │
  └───────┬────────┘             └─────────┬──────────┘                     │
          └──────────────────┬─────────────┴────────────────────────────────┘
                     ┌───────▼────────┐   built from NaoBridgeConfig
                     │   NaoBridge    │   verbs · catalog · on_touch · joints · mic
                     └───────┬────────┘
                             │ NaoRobot Protocol (blocking calls, run off the loop)
                ┌────────────┴─────────────┐
        ┌───────▼───────┐          ┌───────▼───────┐
        │ RealNaoRobot  │          │ FakeNaoRobot  │
        │  qi session   │          │ in-process    │
        └───────┬───────┘          └───────────────┘
                │ tcp://<ip>:9559
          Naoqi (a Nao, or a simulated Naoqi)
```

| Part | Module | Role | Spec |
| --- | --- | --- | --- |
| Config | `config.py` | `NaoBridgeConfig` (backend, robot, streams), the `from_dict` / `from_json` / `from_json_file` loaders, `ConfigError` naming the key | [config.md](config.md) |
| Robot seam | `robot.py` | The `NaoRobot` Protocol (the exact Naoqi slice the bridge consumes), shared constants and types, `RobotConnectionError`, `build_robot(config)` | [robot.md](robot.md) |
| Real backend | `real_robot.py` | `RealNaoRobot`: each Protocol method as Naoqi service calls over a `qi` session, imported lazily; bounded connection attempts | [robot.md](robot.md) |
| Fake backend | `fake_robot.py` | `FakeNaoRobot`: records commands, serves a fixed package list, behaviors that take time, motors that start off, sensor events and paced audio | [robot.md](robot.md) |
| Bridge | `bridge.py`, `errors.py` | `NaoBridge`: lifecycle, verbs that raise why they failed, behavior catalog, running-item tracking, stream APIs | [bridge.md](bridge.md) |
| Event | `events.py` | `Event[T]`: synchronous pub/sub, for occurrences (`bridge.on_touch`) | [events.md](events.md) |
| Observable | `observable.py` | `Observable[T]`: readable and subscribable latest-wins state (`bridge.joints`) | [observable.md](observable.md) |
| Mic feed | `microphone.py` | `MicFeed`: one subscription to Naoqi's pushed audio, a 200-chunk ring, any number of `audio_input()` subscribers | [microphone.md](microphone.md) |
| MCP server | `nao_mcp_server.py` | `NaoMcpServer`: verbs as MCP tools returning status strings; behaviors return once started; stdout reserved for JSON-RPC | [nao-mcp-server.md](nao-mcp-server.md) |
| WebSocket server | `nao_websocket_server.py` | `NaoWebsocketServer` (bridge + listener, one client at a time) and `ClientSession` (the JSON protocol: commands in, touch / joints / audio / log events out) | [nao-websocket-server.md](nao-websocket-server.md) |
| Front door | `__init__.py` | Re-exports what a caller needs: `NaoBridge`, the config classes, the stream values, `Event` / `Observable`, the errors | [bridge.md](bridge.md) |

Dependencies point one way: servers → bridge → seam → backends. `events.py` and `observable.py` import nothing from the project; `config.py` imports neither `qi`, `mcp` nor `websockets`; only `real_robot.py` touches `qi`, and only when it connects.

## Status

Every spec is `Implemented`, and every plan in [plans/_index.md](../plans/_index.md) is `Done`.

| Concept | State |
| --- | --- |
| Config and server configs, `--config` CLIs, example files | Built and tested ([config.md](config.md)) |
| Robot seam, `real` and `fake` backends | Built and tested; `real` verified live on Naoqi 2.1.4.13 / Nao v5 only ([robot.md](robot.md)) |
| `NaoBridge`: verbs, catalog, errors, streams, cancellation | Built and tested ([bridge.md](bridge.md)) |
| `Event`, `Observable`, mic feed | Built and tested ([events.md](events.md), [observable.md](observable.md), [microphone.md](microphone.md)) |
| MCP server | Built and tested ([nao-mcp-server.md](nao-mcp-server.md)) |
| WebSocket server, protocol version 1 | Built and tested ([nao-websocket-server.md](nao-websocket-server.md)) |
| Project tooling, two test tiers, CI | In place ([project.md](project.md), [testing.md](testing.md), [ci.md](ci.md)) |
| Live tier | One smoke test against a real Nao (`NAO_IP`); not in CI |
| Simulated Naoqi as a target | Not built: no `sim` backend, no live CI job (open questions) |

## How a call flows

- **Verbs.** Every verb is `async`. The bridge checks it's running (`NotRunningError`), resolves catalog ids (`ValueError` naming the known ones), asks the robot whether the motors are on when the verb moves the body (`MotorsOffError`), then runs the blocking robot call in `asyncio.to_thread`. A Naoqi exception comes back as `CommandFailedError`, chained. Success returns `None`. Cancelling the awaiting task interrupts any verb. A spanning verb (`say`, the postures, behaviors and the catalog verbs) sends its stop and waits for the robot call to return before re-raising, so the robot has stopped by the time the caller sees the `CancelledError` ([bridge.md](bridge.md) "Cancellation"). So `except (BridgeError, ValueError)` catches every expected failure, and both servers turn exactly those into a readable reason for their client ([bridge.md](bridge.md) "Errors").
- **Long-running behaviors.** On the bridge, `dance`, `expressive_reaction`, `body_action`, `run_app` and `run_behavior` await the behavior's end, and the item shows in `current_*` while it runs; the stop verbs are called concurrently. The servers don't hold their client for minutes: the WebSocket server runs each command as its own task, and the MCP tools return once the item is seen playing ([nao-mcp-server.md](nao-mcp-server.md)).
- **Streams.** Naoqi calls back on its own threads. The bridge marshals touch onto its event loop and re-emits it on `on_touch`; a bridge task samples joints every `period_s` into `joints`; the mic feed writes each pushed buffer into its ring under a lock and wakes its subscribers through `call_soon_threadsafe`. Consumers only ever see the event loop.

## Cross-cutting rules

- **Three stream shapes, chosen by what the data is.** An occurrence where every one matters and nothing replays is an `Event` (touch). A state where only the latest matters is an `Observable` (joints). A continuous signal every consumer needs whole, at its own pace, is a ring with cursors (audio). Each shape has any number of consumers; none is a callback.
- **The config switches streams; the bridge's APIs consume them.** A stream is subscribed on the robot at `start()` only when the config enables it, and using a disabled stream's API raises `BridgeError` ([config.md](config.md)).
- **Every verb is cancellable.** Cancelling the task is the one way to interrupt a verb: the effect it started stops, the cancel returns in bounded time, and the session stays usable. There's no rewind ([bridge.md](bridge.md) "Cancellation").
- **Raise why, not whether.** No verb returns `bool`; each failure has a type and a message an agent can act on.
- **The Protocol is the contract.** pyright checks both backends against `NaoRobot`, so the fake can't drift from what the bridge calls. Units and names at the seam are Naoqi's; intent belongs to the bridge.
- **Fake is the default and honest.** `NaoBridgeConfig()` is the fake; a real robot always means an explicit config with `robot.ip`. The fake behaves like a robot where tests and demos need it (motors start off, behaviors last 5 s, speech 1 s and posture moves 2 s, all stoppable, audio is pushed at Naoqi's pace).
- **Adapters hold no robot logic.** Each server maps its protocol onto bridge verbs and back; logic found in a server belongs in the bridge.
- **The library never configures the process.** Modules log through `logging.getLogger(__name__)`; logging setup, stdout handling and exit codes belong to the CLIs.

## Configuration

One JSON shape, `NaoBridgeConfig`: `backend` (`fake` by default, or `real`), `robot` (`ip`, `port`, `connect_tries`, `connect_timeout_s`) and `streams` (`touch`, `joints`, `audio`, all off by default). Unknown keys, bad types and a `real` backend without an IP fail at load with a `ConfigError` naming the key path. Each server wraps it as `{"bridge": …, "server": …}`, and its CLI takes `--config FILE` only (exit 2 on a bad config, 1 on an unreachable robot). Ready-made files live in `examples/configs/`. Details: [config.md](config.md).

## Packaging and platforms

- Python 3.12–3.13, packaged with uv, `src/` layout; runtime dependencies `mcp<2`, `websockets` and, where a wheel exists, `qi==3.1.6` ([project.md](project.md)).
- `qi` comes from the GitHub Releases of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork, through `[tool.uv.sources]`; PyPI only has the older 3.1.5.

  | Platform | `qi` | Backends |
  | --- | --- | --- |
  | macOS arm64, Linux x86_64 (CPython 3.12 / 3.13) | installed by `uv sync` | `real` and `fake` |
  | Windows, macOS x86_64, Linux aarch64 | absent | `fake` only |

- `nao_bridge` imports everywhere, since `qi` is imported only when `RealNaoRobot` connects.
- uv is the supported installer: pip ignores `[tool.uv.sources]` (open questions).
- Console scripts: `nao-mcp-server`, `nao-websocket-server`.

## Testing and CI

- Two tiers, split by directory ([testing.md](testing.md)): `tests/`, fast and deterministic, runs the bridge and both servers on `FakeNaoRobot` and `RealNaoRobot` against a stub `qi`; `tests-e2e/`, opt-in, runs against a real Nao from `NAO_IP` and skips without it.
- The fast tier makes fake behaviors instant through an autouse fixture; a test that needs a running behavior sets its duration on the fake.
- CI ([ci.md](ci.md)) runs `check` (ruff lint and format, pyright) and `fast-tier` on GitHub's `ubuntu-24.04` runners for every pull request and push to `main`. The Linux runner installs the real `qi` wheel, so the `qi`-gated tests run there.
- `tests/test_project_map.py` keeps [AGENTS.md](../AGENTS.md)'s project map and the specs' frontmatter honest.

## Open questions

Collected from the concept specs, which own them.

- **Simulated Naoqi** ([robot.md](robot.md), [config.md](config.md), [ci.md](ci.md)): a simulated Naoqi is reachable today as `real` at `127.0.0.1`. A `sim` backend name only earns its place if something must tell it apart; a live CI job against a simulator waits until one exists.
- **Newer robots** ([robot.md](robot.md)): only Naoqi 2.1.4.13 / Nao v5 is verified. Nao v6 (Naoqi 2.8) or Pepper may need different service calls inside `RealNaoRobot`; the Protocol shouldn't change.
- **Cancellation** ([bridge.md](bridge.md)): an interruptible connection so a cancelled `start()` doesn't wait out the attempts; whether the newest `say` should interrupt the one in flight; checking live that `stopAll` also stops animated speech's gestures.
- **Microphone** ([microphone.md](microphone.md)): Naoqi's real chunk size at 16 kHz mono is unmeasured (the fake's 1360 samples is a placeholder); 48 kHz four-channel capture and a gap signal in the stream are deferred.
- **Config blocks** ([config.md](config.md)): motion, session state (what the robot does at start and stop) and catalog rules are candidate blocks, added when needed.
- **WebSocket protocol** ([nao-websocket-server.md](nao-websocket-server.md)): no machine-readable schema, no authentication.
- **pip installs** ([project.md](project.md)): pip can't find the `qi` wheels; direct-URL dependencies would fix it but rule out PyPI. Deferred while uv is the supported installer.
- **CI coverage** ([ci.md](ci.md)): Python 3.13 and macOS jobs, deferred until a regression shows the need.
- **Not yet designed:** camera images, perception (faces, people), speech recognition, and how they'd reach agents. None has a spec.
