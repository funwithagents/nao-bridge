---
code:
  - src/naoqi_bridge/__init__.py
  - src/naoqi_bridge/bridge.py
  - src/naoqi_bridge/errors.py
tests:
  - tests/test_bridge.py
  - tests-e2e/test_live_verbs.py
  - tests-e2e/test_live_motion.py
  - tests-e2e/test_live_cancellation.py
  - tests-e2e/test_live_streams.py
---

# The bridge (`NaoqiBridge`)

**Status:** Updated

## Purpose

`NaoqiBridge` is the object a caller holds to drive Nao: intent-level async verbs (say, stand up, dance, react, run an installed app) plus the robot's touch, joint, audio and camera streams. It is built from a [config](config.md) and sits on top of the [robot.md](robot.md) seam, so it runs unchanged on a real robot, a simulated one ([sim.md](sim.md)) or the fake. Every client — the [MCP server](naoqi-mcp-server.md), the [WebSocket server](naoqi-websocket-server.md), or a Python caller — shares this one implementation. It replaces the earlier `NaoAPI` class.

## Core concepts / Decided

### Construction and lifecycle

- `NaoqiBridge(config: NaoqiBridgeConfig | Backend | None = None)` ([config.md](config.md)). With no argument it uses `NaoqiBridgeConfig()`, the offline fake. A bare backend string is shorthand for `NaoqiBridgeConfig(backend=...)`. `NaoqiBridge.from_dict` / `from_json` / `from_json_file` load the config, then build the bridge. Constructing the bridge does nothing else: no connection, no task.
- **`await start()`** on the `sim` backend first acquires the sim: it starts one or borrows the one running, as `sim.spawn` says ([sim.md](sim.md)). Then, on every backend, it builds the robot with `build_robot(config)` ([robot.md](robot.md)) and connects it off the event loop. It subscribes touch, which has no switch ([config.md](config.md), "Streams"), and the streams the config enables (audio through the mic feed, [microphone.md](microphone.md); each enabled camera through its feed, [camera.md](camera.md)), loads the behavior catalog, and starts the joints task when joints are enabled. Last, with `viewer.enabled`, it opens the viewer on the robot it connected to, or logs why not ([viewer.md](viewer.md)). If any step fails, what already started is torn down (the robot closed, the sim released) and the error propagates (`RobotConnectionError` for an unreachable robot or an unavailable sim, `ViewerError` for a viewer that can't launch). Calling `start()` on a running bridge raises `BridgeError`.
- **`await stop()`** closes the viewer if one is open, then cancels the joints task and publishes `None` on `joints`. It then stops the camera feeds (ending every `frames()` subscriber, [camera.md](camera.md)) and the mic feed (which ends every `audio_input()` subscriber), unsubscribes touch, closes the robot, clears the running-item tracking and, last, releases the sim (stopping it when the bridge started it). It tears everything down even if one step fails. It's a no-op when the bridge isn't running, and `start()` may follow it. Cancelling `start()` or `stop()` follows "Cancellation" below: neither leaves anything half up.
- **`async with NaoqiBridge(...) as bridge:`** is shorthand for the pair, and runs `stop()` on every way out.
- `running: bool`. `config` and `backend` (read-only).
- **Escape hatch:** `bridge.robot` is the `NaoqiRobot` — the `FakeNaoqiRobot` on `fake`, which tests use to assert on recorded commands. It raises `NotRunningError` when the bridge isn't running.

### Action verb contract

Every action is `async`, returns `None` when it succeeded, and **raises** to say why it didn't, so a caller (an agent through a server, above all) can act on the reason. Blocking robot calls run in `asyncio.to_thread`. There's no special fake-mode branch: on `fake`, the `FakeNaoqiRobot` answers.

- A verb on a bridge that isn't running raises `NotRunningError`, before anything else is checked.
- **A verb that moves the body needs the motors on.** Before sending its command it asks the robot (`is_awake()`, [robot.md](robot.md)) and raises `MotorsOffError("<verb>: the motors are off; call wake_up() first")` when they're off. The robot is asked every time rather than the bridge tracking `wake_up()` / `rest()`, since the robot can go to rest without the bridge (fall manager, chest button, another client). The check guides the caller; it isn't a guarantee: if the motors go off between the check and the command, Naoqi's own failure arrives as `CommandFailedError`. It runs after the catalog lookup, so an unknown id is still a `ValueError`. The verbs that check: `stand_up`, `sit_down`, `set_breathing_enabled(True, …)`, `run_behavior`, and the catalog verbs `dance`, `expressive_reaction`, `body_action`, `run_app`. The others (`say`, the eyes, the TTS language, basic awareness, `set_breathing_enabled(False, …)`, `wake_up` / `rest` and every stop verb) don't.
- A robot call that raises is re-raised as `CommandFailedError("<verb> failed: <reason>")`, chained to the Naoqi exception (`__cause__`). So is a posture the robot didn't reach (`go_to_posture` returning `False`).
- Cancelling the task that awaits a verb interrupts it, and the robot stops what the verb started ("Cancellation" below). The verb never turns the `CancelledError` into another error.

| Verb | Robot call |
|---|---|
| `set_tts_language(language)` | `set_language` |
| `say(text)` / `stop_say()` | `say` / `stop_speech` |
| `wake_up()` / `rest()` | `wake_up` / `rest` |
| `stand_up()` / `sit_down()` | `go_to_posture("Stand"\|"Sit", 0.8, 3)`; `CommandFailedError` when it returns `False`. Cancelled: `stop_posture` |
| `change_eyes_color(color)` | `fade_eyes` |
| `set_basic_awareness_state(enabled, engagement_mode, tracking_mode)` | `set_basic_awareness` |
| `set_breathing_enabled(enabled, chain_name)` | `set_breathing` |
| `run_behavior(name)` / `stop_behavior(name)` | `run_behavior` (awaits the behavior's end) / `stop_behavior` |

### Behavior catalog

`start()` reads `robot.list_packages()` and classifies it with `build_catalog(packages) -> BehaviorCatalog`. That's a pure function, the same for both backends. It first flattens packages into `NaoqiBehavior(package_uuid, behavior_path, behavior_name, localized_name: LocalizedString(en_US, fr_FR), description, tags)`, where the root behavior (`path == "."`) takes the package's names, description and uuid as its name. Each catalog entry is a `BehaviorInfos(id, behavior_name, localized_name, description)`:

| Catalog | Getter | Selection rule | Id |
|---|---|---|---|
| Dances | `get_dance_behaviors()` | `"dance"` in the description | behavior name |
| Expressive reactions | `get_expressive_reaction_types()` → `["Happy", "Proud", "Laugh", "Sad", "HeadTouched"]` | `animations` package, path starting `Stand/Emotions`, tag `happy` / `proud` / `laugh` / `sad`; `HeadTouched` = `dialog_touch` package, path `animations/head_touched` | reaction type |
| Body actions | `get_body_action_behaviors()` | `dialog_move_arms` package; the name/description comes from the path leaf (`UpLArm` → "Raise left arm", `StretchBothArms` → "Stretch both arms"; `fr_FR` empty) | path leaf |
| Apps | `get_app_behaviors()` | root behavior of a package that's not a system package (`animations`, `boot-config`, `daps`, `default_launchpad_plugins`, `fall-recovery`), not `dialog*`, and not a dance | behavior name |

The classifier doesn't mutate the parsed behaviors, and tolerates packages or behaviors missing a field (a behavior without `langToName` / `langToDesc` / `langToTags` gets empty values; a package without `elems`, `contents`, `names` or `descriptions` is skipped). Getters return an empty list before the first `start()`.

### Catalog verbs and what's running

- `dance(id)`, `body_action(id)` and `run_app(id)` run the entry's behavior and await its end. `expressive_reaction(type)` runs a **random** behavior of that type. An unknown id or type raises `ValueError` naming the known ones (`unknown dance 'macarena' (known: caravan-palace-se, eagle-dance, …)`), so the caller can correct itself without another lookup. A reaction type with no behaviors installed raises `ValueError` too.
- While running, the item is tracked: `current_dances`, `current_body_actions`, `current_apps` and `current_behaviors` are read-only sequences of ids, `current_expressive_reactions` a read-only mapping from type to the behavior actually playing. They are snapshots: a caller can't alter the tracking through them. Tracking is cleared when the run ends or fails. On a cancel it is cleared only once the behavior has stopped, so `current_*` doesn't drop an item the robot is still playing (barring the give-up case in "How a spanning verb stops").
- `stop_dance(id)`, `stop_body_action(id)` and `stop_app(id)` raise `ValueError` for an unknown id and `NotPlayingError` for one that isn't playing; otherwise they stop its behavior. `stop_expressive_reaction(type)` stops **the behavior `expressive_reaction` picked for that type**.
- **A catalog stop verb confirms the stop.** An item is tracked as playing from the moment the bridge hands its behavior to Naoqi, so a stop can land before Naoqi has started it; that first stop finds nothing, and the behavior then plays to its end. So the stop verb sends `stop_behavior`, and if the behavior's run hasn't returned `STOP_RETRY_S` later it sends it again, up to `STOP_ATTEMPTS` stops in all, as a cancelled verb does ("How a spanning verb stops"). It returns once the behavior has stopped, or after the last stop with a warning. A first `stop_behavior` that fails raises `CommandFailedError`; a later one that fails is logged as a warning and ends the wait. Found on Windows, where the thread running the behavior starts later than on Linux or macOS.
- The stop verbs are meant to be called concurrently with the long-running verb they stop.

### Cancellation

Cancelling the task that awaits a verb is the one way to interrupt it, whether the cancel comes from `task.cancel()`, an `asyncio.timeout`, a `TaskGroup` unwinding, or a server dropping a client's request. Every verb honors it. **A cancelled verb guarantees three things:**

1. **The effect stops with the verb.** What the verb started on the robot has stopped *before* the `CancelledError` reaches the caller: the robot is silent, the posture move has stopped, the behavior has ended. The verb stops only what it started.
2. **The cancel returns in bounded time.** The `CancelledError` propagates once the stop is confirmed, which is normally one short Naoqi call. The bound is `STOP_ATTEMPTS × STOP_RETRY_S` (8 × 0.5 s, 4 s); see "How a spanning verb stops" below.
3. **The robot and the session stay usable.** The cancel undoes only that verb's own effect. The motor state, the eyes, breathing and basic awareness stay as they were, the streams keep running, and the next verb works at once: a cancelled `dance` can be followed by another `dance` straight away.

It does **not** mean rewind. What already happened stays done: the words already spoken were heard, and a posture move or a dance stops where the cancel caught it. The robot doesn't go back to where it started.

#### Two classes of verbs

**Spanning verbs** last as long as their effect on the robot, and they are where the guarantees above do real work:

| Verb | Robot call it spans | Stop sent on cancel |
|---|---|---|
| `say(text)` | `say` (returns when spoken) | `stop_speech` |
| `stand_up()` / `sit_down()` | `go_to_posture` | `stop_posture` |
| `run_behavior(name)` | `run_behavior` (returns when the behavior ends) | `stop_behavior(name)` |
| `dance`, `expressive_reaction`, `body_action`, `run_app` | `run_behavior` of the entry's behavior | `stop_behavior` of that behavior (for a reaction, the one `expressive_reaction` picked) |

**Instant verbs** hand Naoqi one command and return: `set_tts_language`, `change_eyes_color`, `set_basic_awareness_state`, `set_breathing_enabled`, `wake_up` / `rest`, `stop_say` and `stop_behavior`. A cancel returns at once. The command already handed to Naoqi still runs to its end in its thread: it can't be interrupted, and none of these has a stop. If the effect lasts beyond the call, it is a *mode*, and the verb's counterpart switches it back, not a cancel. `wake_up` and `rest` take a few seconds on a robot (`rest` crouches first) but are instant verbs all the same: a half-applied `rest` would leave the motors in an unknown state, so the call completes, and `wake_up` undoes it.

Each verb belongs to exactly one class, so no verb leaves an effect running that neither a cancel nor a counterpart verb can stop.

The streams have their own cancellation contracts: an `audio_input()` subscriber ([microphone.md](microphone.md)), a camera feed's `frames()` ([camera.md](camera.md)) and an `Observable.changes()` iteration ([observable.md](observable.md)) each end when their task is cancelled.

#### How a spanning verb stops

- **Cancelled before the command is sent**, for example during the motors check: nothing reached the robot, so there's nothing to stop, and the `CancelledError` propagates at once.
- **Cancelled while the robot call runs:** the call is already running in its thread (`asyncio.to_thread`) and can't be interrupted, so the bridge sends the verb's stop call off the event loop, then waits for the spanned call to return. The behavior has ended and the speech is silent once that call returns. Only then is the item's tracking cleared and the `CancelledError` re-raised.
- **Stop re-sent:** a cancel (or a catalog stop verb, above) can land before Naoqi has started the command, so the first stop finds nothing to stop and the command then runs anyway. So if the spanned call hasn't returned `STOP_RETRY_S` (0.5 s) after a stop, the stop is sent again, up to `STOP_ATTEMPTS` (8) stops in all, so the bridge waits up to 4 s for the robot to confirm. NAOqi itself can take more than 2 s to end a stopped command: measured on a simulated Nao (NAOqi's own `ALRobotPosture`), `goToPosture` returns about 2.4 s after `stopMove` on 2.1 and 2.8; the bound leaves room for it. (Speech stops at once, through `ALAnimatedSpeech`'s own stop: [robot.md](robot.md).) If the call still hasn't returned, the bridge logs a warning naming the verb, stops waiting (the thread is left to finish on its own), clears the tracking and re-raises.
- **The stop is owned:** a second cancel arriving while the bridge stops the verb doesn't cut the stop short. It is absorbed until the stop is done, then the `CancelledError` propagates.
- **What the stop sees is not the caller's business:** a stop call that raises is logged as a warning and ends the wait. Whatever the spanned call returns or raises after the stop (a posture reported not reached, a Naoqi "behavior stopped" error) is dropped. The caller always gets the `CancelledError` and never a `CommandFailedError`.

#### Lifecycle

- **A cancel during `start()` is handled like a failure.** A connection in flight gives up: `start()` passes the robot's `connect()` a `threading.Event` and sets it on the cancel, so the attempt ends within one 50 ms poll ([robot.md](robot.md)). Any other step in flight finishes in its thread, since it can't be interrupted. Then everything started so far is torn down, the robot is closed if it connected, and the `CancelledError` propagates. Nothing is leaked; the cancel takes as long as the step in flight, which is short once the connection is up. Acquiring a sim is cancel-safe on its own ([sim.md](sim.md), "`sim.py`: the lease"): a sim being started is stopped before the cancel propagates, which takes the seconds a `compose up` in flight needs to finish.
- **`stop()` is owned once begun.** A cancel arriving while it runs is absorbed until every teardown step has run, then propagates. The bridge reads as not running from the moment `stop()` begins.

### Streams

The config's `streams` block decides what `start()` subscribes to on the robot ([config.md](config.md)); touch has no switch and is always subscribed. Each stream is consumed through its own API, open to any number of consumers. The objects below belong to the bridge and outlive its sessions.

| Stream | API | Contract |
|---|---|---|
| touch | `bridge.on_touch: Event[TouchEvent]` ([events.md](events.md)) | `TouchEvent(part: TouchPart, touched: bool)`; `TouchPart` is the `Literal` of `FrontTactilTouched` / `MiddleTactilTouched` / `RearTactilTouched`, so a handler can match on it under pyright. Naoqi fires on its own thread, and the bridge re-emits on its event loop (`call_soon_threadsafe`), so handlers run on the loop. Always on: there is no switch, since subscribing costs nothing. A subscription that fails at `start()` is logged as a warning and `on_touch` stays silent: touch is never essential, so a Naoqi without the tactile keys still starts. |
| joints | `bridge.joints: Observable[JointsState \| None]` ([observable.md](observable.md)) | `JointsState(names, angles, ts)`, angles in radians, `ts` on the monotonic clock, `set` every `streams.joints.period_s` by a bridge task. `None` outside a session. A failing read is logged and the loop continues. Disabled: reading `joints` raises `BridgeError`. |
| audio | `bridge.audio_input(preroll_s=0.0)`, `bridge.mic` ([microphone.md](microphone.md)) | Each call is a subscriber yielding int16 LE mono `bytes` at `mic.sample_rate` (16000). `mic.latest()` and `published_count` are for samplers. Disabled: `audio_input()` raises `BridgeError` at the call; bridge not running: `NotRunningError`. |
| cameras | `bridge.cameras["top"]`, `bridge.cameras["bottom"]`: `CameraFeed` ([camera.md](camera.md)) | `latest()` is the newest `CameraFrame` (BGR `data`, a numpy `image` view, `camera_transform` camera → FRAME_ROBOT, `fov`) or `None`; `frames()` is a latest-wins iterator ending with the session; `published_count` for samplers. Both feeds exist from construction. Disabled: `frames()` / `wait_for` raise `BridgeError` at the call, `latest()` is `None`; bridge not running: `NotRunningError`. |

### Errors

Defined in `errors.py`, so the bridge's modules share them; `bridge.py` doesn't re-export them, the front door does.

| Error | Raised for |
|---|---|
| `BridgeError(RuntimeError)` | The base of the bridge's own errors. Raised as such for lifecycle and stream misuse: a double `start()`, a disabled stream's API. |
| `NotRunningError(BridgeError)` | A verb, `robot`, `audio_input()` or a camera feed's `frames()` on a bridge that isn't running. |
| `NotPlayingError(BridgeError)` | A catalog stop verb for an item that isn't playing. |
| `MotorsOffError(BridgeError)` | A verb that moves the body while the motors are off (see "Action verb contract"). |
| `CommandFailedError(BridgeError)` | The robot failed a verb: a Naoqi exception (chained), or a posture not reached. |
| `ViewerError(BridgeError)` | `start()` couldn't launch the viewer: naoqi-viewer's `LaunchError`, chained ([viewer.md](viewer.md), "Errors"). |
| `ValueError` | Bad input: a catalog id or reaction type the catalog doesn't hold, or a reaction type with no behaviors installed. |

So `except (BridgeError, ValueError)` catches every expected verb failure, and that's what both servers do. `ConfigError` comes from [config.md](config.md). `RobotConnectionError` from [robot.md](robot.md) propagates out of `start()`; raised by a verb's robot call, it's wrapped in `CommandFailedError` like any robot failure.

### Front door and logging

`from naoqi_bridge import NaoqiBridge` re-exports what a caller needs:
- `NaoqiBridge`;
- the config classes (`NaoqiBridgeConfig`, `RobotSettings`, `StreamSettings`, `JointsStream`, `AudioStream`, `CameraStreams`, `CameraStream`, `CameraResolution`, `SimSettings`, `ViewerSettings`, `Backend`, `SimSpawn`);
- the stream values (`TouchEvent`, `TouchPart`, `JointsState`, `MicChunk`, `CameraFrame`, `Camera`) and the `Event` / `Observable` types;
- `BehaviorInfos`, `LocalizedString`;
- the errors (`BridgeError`, `NotRunningError`, `NotPlayingError`, `MotorsOffError`, `CommandFailedError`, `ViewerError`, `ConfigError`, `RobotConnectionError`). Library modules only use `logging.getLogger(__name__)`; `logging.basicConfig` belongs to the CLIs.

## Open questions

1. **Concurrent `say` calls.** Two overlapping `say` calls are queued or mixed by Naoqi as it sees fit. Whether the newest `say` should interrupt the one in flight is deferred. Cancelling one `say` stops the speech (`ALTextToSpeech.stopAll`), and that silences the other too.
2. **`stopAll` and animated speech.** It's assumed (not yet verified live on Naoqi 2.1.4.13) that `ALTextToSpeech.stopAll` makes `ALAnimatedSpeech.say` return and stops its gestures. If the gestures play on, the `say` row needs an `ALAnimatedSpeech`-level stop.
