---
code:
  - src/nao_bridge/nao_api.py
tests:
---

# NaoAPI

**Status:** Updated

> Retro-documented from existing code when the SDD workflow was adopted. Status is `Updated` rather than `Implemented` because of one known defect (see "Known gaps"), tracked by [plans/202610071900_existing-code-to-green.md](../plans/202610071900_existing-code-to-green.md).

## Purpose

The single place that talks to the robot. `NaoAPI` wraps a Naoqi `qi` session and its services behind intent-level async methods (say, stand up, dance, react, run an app) so every client — the MCP server, the WebSocket server, or a direct Python caller — shares one implementation. A fake-robot mode lets everything above it run without hardware or the `qi` wheel.

## Core concepts / Decided

### Construction and connection

- `NaoAPI(fake_robot, memory_callback_touch, joints_callback, audio_callback, nao_ip="", nao_port=9559)`. Each callback is optional (`None` disables that stream) and is an **async** function invoked on the event loop that called `connect()`.
- `async connect() -> bool`:
  - `fake_robot=True` → loads the fake behavior catalog, returns `True`. No `qi` import is needed.
  - `qi` not importable → logs an error, **switches to fake mode** (`fake_robot = True`), loads the fake catalog, returns `True`.
  - Real mode with empty IP or port `0` → returns `False` (fake catalog loaded so getters still return data).
  - Otherwise opens `tcp://<ip>:<port>` (up to 10 tries), acquires the Naoqi services (`ALMemory`, `ALAutonomousLife`, `PackageManager`, `ALBehaviorManager`, `ALMotion`, `ALRobotPosture`, `ALLeds`, `ALTextToSpeech`, `ALAnimatedSpeech`, `ALBasicAwareness`, `ALAudioDevice`), starts the enabled streams, builds the real behavior catalog, sets `connected = True`.
- `async disconnect() -> bool`: no-op returning `True` in fake mode or when not connected; otherwise stops the streams and closes the session.

### Action method contract

Every action is `async` and returns `bool` (success). It never raises — exceptions from Naoqi are logged and turned into `False`. Blocking Naoqi calls run in `asyncio.to_thread`.

- **Fake mode:** every action returns `True` without touching hardware.
- **Real mode, not connected:** returns `False`.
- **Catalog-keyed actions validate the id first**, *before* the fake/connection check: an unknown dance/reaction/body-action/app id returns `False` even in fake mode. Stop-variants additionally require the id to be currently running (in real mode).

| Method | Naoqi call |
|---|---|
| `set_tts_language(language)` | `ALTextToSpeech.setLanguage` |
| `say(text)` / `stop_say()` | `ALAnimatedSpeech.say` / `ALTextToSpeech.stopAll` |
| `wake_up()` / `rest()` | `ALMotion.wakeUp` / `ALMotion.rest` |
| `stand_up()` / `sit_down()` | `ALRobotPosture.goToPosture("Stand"\|"Sit", 0.8)`, max 3 tries; returns the posture result |
| `change_eyes_color(color)` | `ALLeds.fadeRGB("FaceLeds", color, 0)` |
| `set_basic_awareness_state(enabled, engagement_mode, tracking_mode)` | `ALBasicAwareness` set modes, then start/stop |
| `set_breathing_enabled(enabled, chain_name)` | `ALMotion.setBreathEnabled` |
| `run_behavior(name)` / `stop_behavior(name)` | `ALBehaviorManager.runBehavior` (awaits completion) / `stopBehavior` |

`run_behavior` resolves only when the behavior **ends**, so `dance`, `expressive_reaction`, `body_action` and `run_app` are long-running awaits; their stop-counterparts are meant to be called concurrently.

### Behavior catalog

Built once at connect from `PackageManager.packages2()` into `NaoBehavior` records (`package_uuid`, `behavior_path`, `behavior_name`, `localized_name: LocalizedString(en_US, fr_FR)`, `description`, `tags`), then classified into `BehaviorInfos(id, behavior_name, localized_name, description)`:

| Catalog | Getter | Selection rule | Id |
|---|---|---|---|
| Dances | `get_dance_behaviors()` | `"dance"` in description | behavior name |
| Expressive reactions | `get_expressive_reaction_types()` → `["Happy","Proud","Laugh","Sad","HeadTouched"]` | `animations` package, `Stand/Emotions…` path, tag `happy`/`proud`/`laugh`/`sad`; `HeadTouched` = `dialog_touch/animations/head_touched` | reaction type; `expressive_reaction` plays a **random** behavior of that type |
| Body actions | `get_body_action_behaviors()` | `dialog_move_arms` package; description derived from the path leaf (`UpLArm` → "Raise left arm") | path leaf |
| Apps | `get_app_behaviors()` | root behavior (`path == "."`) of packages not in the system set (`animations`, `boot-config`, `daps`, `default_launchpad_plugins`, `fall-recovery`), not `dialog*`, not a dance | behavior name |

In fake mode the catalog is a fixed set: 4 dances, the 5 reaction types with **empty** lists (so `expressive_reaction` returns `False` even in fake mode), 6 body actions, 4 apps.

Running items are tracked in `current_dances`, `current_expressive_reactions`, `current_body_actions`, `current_apps`, `current_behaviors`.

### Sensor streams (real mode only)

- **Touch:** subscribes to `FrontTactilTouched`, `MiddleTactilTouched`, `RearTactilTouched`; calls `memory_callback_touch(key, value)` with `value` 0/1.
- **Joints:** every 0.2 s, `joints_callback(names, angles)` from `ALMotion.getBodyNames/getAngles("Body")`.
- **Audio:** registers itself as a Naoqi service and subscribes to `ALAudioDevice` at 16 kHz; Naoqi calls `processRemote(...)` (name mandated by Naoqi), which forwards `audio_callback(16000, channels, samples_per_channel, base64_pcm16le)`.
- Callbacks fired from Naoqi threads are marshalled onto the connect-time loop with `run_coroutine_threadsafe`.

## Known gaps

1. **`stop_expressive_reaction` stops the wrong thing:** it passes the reaction *list* (`_expressive_reaction_behaviors[type]`) to `stop_behavior` instead of the running behavior name recorded in `current_expressive_reactions[type]`. Intended behavior: stop the behavior that `expressive_reaction` started. This is why the spec is `Updated`.
2. `_retrieve_body_actions` mutates the shared `NaoBehavior` records (overwrites `localized_name`/`description`) — harmless today, but a side effect.
3. `async_api` is a dead helper missing `self`.

## Open questions

1. **Newer Naoqi / robots.** Only verified on Naoqi 2.1.4.13 / Nao v5; Nao v6 or Pepper may need API adjustments.
2. **Reaction catalog in fake mode** is empty, so reactions can't be exercised without a robot — add fake reaction behaviors?
3. **Module-level `logging.basicConfig`** configures the root logger on import, which a library shouldn't do — move to the CLI entry points?
