---
code:
  - src/nao_bridge/__init__.py
  - src/nao_bridge/bridge.py
tests:
  - tests/test_bridge.py
---

# The bridge (`NaoBridge`)

**Status:** Implemented

## Purpose

`NaoBridge` is the object a caller holds to drive Nao: intent-level async verbs (say, stand up, dance, react, run an installed app) plus the robot's touch, joint and audio streams. It sits on top of the [robot.md](robot.md) seam, so it runs unchanged on a real robot or the fake. Every client — the [MCP server](nao-mcp-server.md), the [WebSocket server](nao-websocket-server.md), or a Python caller — shares this one implementation. It replaces the earlier `NaoAPI` class and mirrors the sibling reachy-mini-bridge project's `ReachyMiniBridge`.

## Core concepts / Decided

### Construction and lifecycle

- `NaoBridge(backend="real", *, ip="", port=9559, on_touch=None, on_joints=None, on_audio=None)`. `backend` is `"real"` or `"fake"` ([robot.md](robot.md)). Constructing the bridge does nothing else: no connection, no task.
- **`await start()`** builds the robot with `build_robot(backend, ip=ip, port=port)`, connects it off the event loop, and subscribes the streams that have a callback (touch, audio). It then loads the behavior catalog and starts the joints task when `on_joints` is set. If any step fails, what already started is torn down (the robot closed) and the error propagates (`RobotConnectionError` for an unreachable robot). Calling `start()` on a running bridge raises `BridgeError`.
- **`await stop()`** cancels the joints task, unsubscribes the streams, closes the robot, and clears the running-item tracking. It tears everything down even if one step fails. It's a no-op when the bridge isn't running, and `start()` may follow it.
- **`async with NaoBridge(...) as bridge:`** is shorthand for the pair, and runs `stop()` on every way out.
- `running: bool`. `backend` (read-only).
- **Escape hatch:** `bridge.robot` (alias `bridge.raw`) is the `NaoRobot` — the `FakeNaoRobot` on `fake`, which tests use to assert on recorded commands. It raises `BridgeError` when the bridge isn't running.

### Action verb contract

Every action is `async` and returns `bool` (success). Verbs **never raise** — a robot exception is logged and becomes `False`. Blocking robot calls run in `asyncio.to_thread`. A verb on a bridge that isn't running returns `False`. There's no special fake-mode branch: on `fake`, the `FakeNaoRobot` answers.

| Verb | Robot call |
|---|---|
| `set_tts_language(language)` | `set_language` |
| `say(text)` / `stop_say()` | `say` / `stop_speech` |
| `wake_up()` / `rest()` | `wake_up` / `rest` |
| `stand_up()` / `sit_down()` | `go_to_posture("Stand"\|"Sit", 0.8, 3)`; returns the posture result |
| `change_eyes_color(color)` | `fade_eyes` |
| `set_basic_awareness_state(enabled, engagement_mode, tracking_mode)` | `set_basic_awareness` |
| `set_breathing_enabled(enabled, chain_name)` | `set_breathing` |
| `run_behavior(name)` / `stop_behavior(name)` | `run_behavior` (awaits the behavior's end) / `stop_behavior` |

### Behavior catalog

`start()` reads `robot.list_packages()` and classifies it with `build_catalog(packages) -> BehaviorCatalog`. That's a pure function, the same for both backends. It first flattens packages into `NaoBehavior(package_uuid, behavior_path, behavior_name, localized_name: LocalizedString(en_US, fr_FR), description, tags)`, where the root behavior (`path == "."`) takes the package's names, description and uuid as its name. Each catalog entry is a `BehaviorInfos(id, behavior_name, localized_name, description)`:

| Catalog | Getter | Selection rule | Id |
|---|---|---|---|
| Dances | `get_dance_behaviors()` | `"dance"` in the description | behavior name |
| Expressive reactions | `get_expressive_reaction_types()` → `["Happy", "Proud", "Laugh", "Sad", "HeadTouched"]` | `animations` package, path starting `Stand/Emotions`, tag `happy` / `proud` / `laugh` / `sad`; `HeadTouched` = `dialog_touch` package, path `animations/head_touched` | reaction type |
| Body actions | `get_body_action_behaviors()` | `dialog_move_arms` package; the name/description comes from the path leaf (`UpLArm` → "Raise left arm", `StretchBothArms` → "Stretch both arms"; `fr_FR` empty) | path leaf |
| Apps | `get_app_behaviors()` | root behavior of a package that's not a system package (`animations`, `boot-config`, `daps`, `default_launchpad_plugins`, `fall-recovery`), not `dialog*`, and not a dance | behavior name |

The classifier doesn't mutate the parsed behaviors. Getters return an empty list before the first `start()`.

### Catalog verbs and what's running

- `dance(id)`, `body_action(id)` and `run_app(id)` run the entry's behavior and await its end. `expressive_reaction(type)` runs a **random** behavior of that type. An unknown id/type returns `False`; so does a reaction type with no behaviors.
- While running, the item is tracked in `current_dances`, `current_body_actions`, `current_apps` (lists of ids), `current_expressive_reactions` (type → the behavior actually playing) and `current_behaviors`. Tracking is cleared when the run ends, fails or is cancelled.
- `stop_dance(id)`, `stop_body_action(id)` and `stop_app(id)` return `False` for an unknown id or one that isn't running; otherwise they stop its behavior. `stop_expressive_reaction(type)` stops **the behavior `expressive_reaction` picked for that type**.
- The stop verbs are meant to be called concurrently with the long-running verb they stop.

### Streams

Callbacks are optional `async` functions, scheduled on the event loop that called `start()`. Robot events arrive on robot threads and are marshalled with `run_coroutine_threadsafe`.

- `on_touch(key, value)`: `key` ∈ `FrontTactilTouched` / `MiddleTactilTouched` / `RearTactilTouched`, `value` 0/1.
- `on_joints(names, angles)`: every 0.2 s from a bridge task, angles in radians. A failing read is logged and the loop continues.
- `on_audio(rate, channels, samples_per_channel, data)`: `rate` 16000, `data` base64 of 16-bit little-endian PCM.

### Errors

`BridgeError(RuntimeError)`: lifecycle misuse (double `start()`, `robot` while stopped). `RobotConnectionError` from [robot.md](robot.md) propagates out of `start()`. Verbs return `False` rather than raising.

### Front door and logging

`from nao_bridge import NaoBridge` re-exports `NaoBridge`, `BridgeError`, `BehaviorInfos`, `LocalizedString`, `RobotConnectionError`, `Backend`. Library modules only use `logging.getLogger(__name__)`; `logging.basicConfig` belongs to the CLIs.

## Open questions

1. **Raise instead of `bool`?** `ReachyMiniBridge` raises (`ValueError`, `BridgeError` subclasses), which carries *why* a verb failed. Switching would also change both servers' result mapping. This is a deferral: `bool` works today.
2. **Callbacks vs observables.** Reachy exposes streams as `Observable`s that any number of consumers can subscribe to. Nao's three single-consumer callbacks are enough for the two servers today.
3. **Config object.** A `NaoBridgeConfig` (from dict/JSON) like reachy's only pays off once there are more knobs than backend/ip/port/streams.
