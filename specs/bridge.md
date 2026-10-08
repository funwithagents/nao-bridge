---
code:
  - src/nao_bridge/__init__.py
  - src/nao_bridge/bridge.py
  - src/nao_bridge/errors.py
tests:
  - tests/test_bridge.py
---

# The bridge (`NaoBridge`)

**Status:** Implemented

## Purpose

`NaoBridge` is the object a caller holds to drive Nao: intent-level async verbs (say, stand up, dance, react, run an installed app) plus the robot's touch, joint and audio streams. It is built from a [config](config.md) and sits on top of the [robot.md](robot.md) seam, so it runs unchanged on a real robot or the fake. Every client — the [MCP server](nao-mcp-server.md), the [WebSocket server](nao-websocket-server.md), or a Python caller — shares this one implementation. It replaces the earlier `NaoAPI` class.

## Core concepts / Decided

### Construction and lifecycle

- `NaoBridge(config: NaoBridgeConfig | Backend | None = None)` ([config.md](config.md)). With no argument it uses `NaoBridgeConfig()`, the offline fake. A bare backend string is shorthand for `NaoBridgeConfig(backend=...)`. `NaoBridge.from_dict` / `from_json` / `from_json_file` load the config, then build the bridge. Constructing the bridge does nothing else: no connection, no task.
- **`await start()`** builds the robot with `build_robot(config)` ([robot.md](robot.md)) and connects it off the event loop. It subscribes the streams the config enables (touch; audio through the mic feed, [microphone.md](microphone.md)), loads the behavior catalog, and starts the joints task when joints are enabled. If any step fails, what already started is torn down (the robot closed) and the error propagates (`RobotConnectionError` for an unreachable robot). Calling `start()` on a running bridge raises `BridgeError`.
- **`await stop()`** cancels the joints task and publishes `None` on `joints`. It then stops the mic feed (which ends every `audio_input()` subscriber), unsubscribes touch, closes the robot, and clears the running-item tracking. It tears everything down even if one step fails. It's a no-op when the bridge isn't running, and `start()` may follow it.
- **`async with NaoBridge(...) as bridge:`** is shorthand for the pair, and runs `stop()` on every way out.
- `running: bool`. `config` and `backend` (read-only).
- **Escape hatch:** `bridge.robot` is the `NaoRobot` — the `FakeNaoRobot` on `fake`, which tests use to assert on recorded commands. It raises `BridgeError` when the bridge isn't running.

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

The config's `streams` block decides what `start()` subscribes to on the robot ([config.md](config.md)). Each stream is consumed through its own API, open to any number of consumers. The objects below belong to the bridge and outlive its sessions.

| Stream | API | Contract |
|---|---|---|
| touch | `bridge.on_touch: Event[TouchEvent]` ([events.md](events.md)) | `TouchEvent(part, touched: bool)`; `part` ∈ `FrontTactilTouched` / `MiddleTactilTouched` / `RearTactilTouched`. Naoqi fires on its own thread, and the bridge re-emits on its event loop (`call_soon_threadsafe`), so handlers run on the loop. Disabled: it simply never emits. |
| joints | `bridge.joints: Observable[JointsState \| None]` ([observable.md](observable.md)) | `JointsState(names, angles, ts)`, angles in radians, `ts` on the monotonic clock, `set` every `streams.joints.period_s` by a bridge task. `None` outside a session. A failing read is logged and the loop continues. Disabled: reading `joints` raises `BridgeError`. |
| audio | `bridge.audio_input(preroll_s=0.0)`, `bridge.mic` ([microphone.md](microphone.md)) | Each call is a subscriber yielding int16 LE mono `bytes` at `mic.sample_rate` (16000). `mic.latest()` and `published_count` are for samplers. Disabled, or bridge not running: `audio_input()` raises `BridgeError` at the call. |

### Errors

`BridgeError(RuntimeError)` (in `errors.py`, so the bridge's modules share it): lifecycle and stream misuse (double `start()`, `robot` while stopped, a disabled stream's API). `ConfigError` comes from [config.md](config.md). `RobotConnectionError` from [robot.md](robot.md) propagates out of `start()`. Verbs return `False` rather than raising.

### Front door and logging

`from nao_bridge import NaoBridge` re-exports what a caller needs:
- `NaoBridge`;
- the config classes (`NaoBridgeConfig`, `RobotSettings`, `StreamSettings`, `TouchStream`, `JointsStream`, `AudioStream`, `Backend`);
- the stream values (`TouchEvent`, `JointsState`, `MicChunk`) and the `Event` / `Observable` types;
- `BehaviorInfos`, `LocalizedString`;
- the errors (`BridgeError`, `ConfigError`, `RobotConnectionError`). Library modules only use `logging.getLogger(__name__)`; `logging.basicConfig` belongs to the CLIs.

## Open questions

1. **Raise instead of `bool`?** Raising (`ValueError` for bad input, `BridgeError` subclasses for state errors) would tell the caller *why* a verb failed. Switching would also change both servers' result mapping. This is a deferral: `bool` works today.
