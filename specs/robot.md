---
code:
  - src/nao_bridge/robot.py
  - src/nao_bridge/real_robot.py
  - src/nao_bridge/fake_robot.py
tests:
  - tests/test_robot.py
  - tests/test_real_robot.py
  - tests/test_fake_robot.py
  - tests-e2e/test_live_robot.py
---

# Robot (connection seam)

**Status:** Implemented

## Purpose

The seam between Nao Bridge and a Naoqi robot. It lets the layer above ([bridge.md](bridge.md)) run unchanged against a real Nao (over a `qi` session) or a first-party fake, chosen by a backend string.

The seam delivers two things:

1. **Testability.** A real robot needs hardware, a network and the `qi` wheel. The fast `tests/` tier ([testing.md](testing.md)) runs the whole stack — bridge, MCP server, WebSocket server — against `FakeNaoRobot`, with none of the three.
2. **A pinned slice.** The `NaoRobot` Protocol lists exactly the Naoqi capabilities the bridge consumes. pyright checks both implementations against it, so the fake can't drift from what the bridge calls.

## Core concepts / Decided

### A Protocol, not a union over the SDK object

A seam can be a type union over an SDK's robot class and a fake, checked by pyright. That doesn't work for Naoqi: it has no single robot class. `qi.Session` is an untyped RPC session handing out services by name (`session.service("ALMotion")`). Also, `qi` isn't on PyPI, so pyright and CI can't see it.

So the seam is a **first-party `NaoRobot` Protocol**, with two implementations:

| Backend | Class | What it is |
|---|---|---|
| `real` (default) | `RealNaoRobot(ip, port=9559, *, connect_tries=10, connect_timeout_s=5.0)` | Translates each Protocol method into the Naoqi service call(s) |
| `fake` | `FakeNaoRobot()` | Records every command, serves a fixed package list, simulates behavior runs and sensor events |

Each lives in its own module: `robot.py` holds what they share (the Protocol, the callback types, `TOUCH_KEYS` / `AUDIO_SAMPLE_RATE` / `AUDIO_CHANNEL_CODES`, `RobotConnectionError`) and `build_robot`; `real_robot.py` holds `RealNaoRobot`; `fake_robot.py` holds `FakeNaoRobot` and its package list. `build_robot` imports the two lazily, since both import `robot.py`.

The Protocol is the contract; each implementation translates it to its backend. Units and names at this layer are Naoqi's. Intent-level semantics (catalog, reactions, tracking what's running) belong to [bridge.md](bridge.md).

### `build_robot(config: NaoBridgeConfig) -> NaoRobot`

The one way in, used by `NaoBridge.start()`, driven by the [config](config.md):
- `backend: "fake"` → `FakeNaoRobot()`; the `robot` block is ignored.
- `backend: "real"` → `RealNaoRobot(robot.ip, robot.port, connect_tries=robot.connect_tries, connect_timeout_s=robot.connect_timeout_s)`.

The config has already rejected unknown backends and a `real` backend without an IP. Building does not connect.

### The consumed slice

Every method is **blocking** (the bridge calls them via `asyncio.to_thread`) and **raises** on failure; the bridge turns failures into its own results.

| Method | `RealNaoRobot` → Naoqi |
|---|---|
| `connect()` / `close()` | open / close `tcp://<ip>:<port>` |
| `set_language(language)` | `ALTextToSpeech.setLanguage` |
| `say(text)` | `ALAnimatedSpeech.say` (returns when spoken) |
| `stop_speech()` | `ALTextToSpeech.stopAll` |
| `wake_up()` / `rest()` | `ALMotion.wakeUp` / `rest` |
| `go_to_posture(posture, speed, max_tries) -> bool` | `ALRobotPosture.setMaxTryNumber` + `goToPosture` |
| `set_breathing(chain_name, enabled)` | `ALMotion.setBreathEnabled` |
| `fade_eyes(color)` | `ALLeds.fadeRGB("FaceLeds", color, 0)` |
| `set_basic_awareness(enabled, engagement_mode, tracking_mode)` | `ALBasicAwareness` set modes, then `startAwareness` / `stopAwareness` |
| `list_packages() -> list[dict]` | `PackageManager.packages2()` (raw Naoqi package dicts) |
| `run_behavior(name)` | `ALBehaviorManager.runBehavior` (returns when the behavior **ends**) |
| `stop_behavior(name)` | `ALBehaviorManager.stopBehavior` |
| `get_joints() -> (names, angles)` | `ALMotion.getBodyNames("Body")`, `getAngles("Body", False)` (radians) |
| `subscribe_touch(cb)` / `unsubscribe_touch()` | `ALMemory` subscribers on `FrontTactilTouched`, `MiddleTactilTouched`, `RearTactilTouched`; `cb(key, value)` |
| `subscribe_audio(cb, channel)` / `unsubscribe_audio()` | registers an audio sink service, `ALAudioDevice.setClientPreferences(…, 16000, code, 0)` with `code` for the `channel` microphone (`left` 1, `right` 2, `front` 3, `rear` 4), + `subscribe`; `cb(channels, samples_per_channel, pcm16le_bytes)`. Its only caller is the mic feed ([microphone.md](microphone.md)). |

Sensor callbacks are invoked **on Naoqi's threads**; marshalling onto an event loop is the bridge's job.

### `RealNaoRobot`

- **`qi` is imported lazily in `connect()`** (via `importlib`), so importing `nao_bridge` never needs it. `qi` is a dependency on the platforms with a wheel and absent elsewhere ([project.md](project.md)). If it's missing, `connect()` raises `RobotConnectionError`: the message names the platforms that ship `qi` (macOS arm64, Linux x86_64, CPython 3.12 / 3.13), says to run `uv sync` there, and says the platform otherwise runs the `fake` backend only. **There is no silent fallback to fake** — that was the old behavior, and it let an agent believe a real robot was moving. Ask for the fake explicitly.
- `connect()` with an empty IP or a non-positive port raises `RobotConnectionError` before trying.
- `connect()` makes up to `connect_tries` attempts (default 10, from the config), each **bounded by `connect_timeout_s`** (default 5 s). An attempt connects asynchronously (`session.connect(url, _async=True)` → a `qi.Future`) and waits on the future with that deadline:
  - **Finished without error:** connected.
  - **Finished with an error** (refused port, unreachable network): the session is closed and the next attempt starts at once.
  - **Still running at the deadline** (a silent host, which a blocking connect would wait out for the OS TCP timeout, ~76 s): the future is cancelled, the session closed, and the next attempt starts.

  After the last attempt it raises `RobotConnectionError` naming the attempts, chained to the last error. A wrong IP therefore fails within `connect_tries × connect_timeout_s` (50 s by default).
- Services are acquired lazily on first use and cached for the session; `close()` drops them.
- Naoqi requires the audio sink to expose a method named exactly `processRemote`. That lives on a small private sink object, so `RealNaoRobot`'s own surface stays the Protocol.

### `FakeNaoRobot`

What the fake does is set by what the tests exercise:

- **Recording:** each Protocol call appends `(method_name, {args})` to `commands`; `connected` mirrors `connect()`/`close()`.
- **Package list:** `list_packages()` returns a fixed `packages2`-shaped list. The bridge classifies it with the same code it uses for a real robot. It yields 4 dances, 4 apps, 6 arm actions, and reactions for every type (`Happy`, `Proud`, `Laugh`, `Sad`, `HeadTouched`), plus a `Sit/` emotion that the classifier must ignore. Every package has an `en_US`/`fr_FR` name and an `en_US` description, and comes in one of two shapes: root packages (one behavior at `path == "."`, which takes the package's name and description, as dances and apps do) and sub-behavior packages (several behaviors at their own paths, as `animations`, `dialog_touch` and `dialog_move_arms` are).
- **Behavior runs:** a behavior takes time, as on a robot. `run_behavior` blocks for `behavior_duration_s`, which defaults to `DEFAULT_BEHAVIOR_DURATION_S = 5.0` s, or until `stop_behavior(name)` (or `close()`) ends it. So on the fake, dances, body actions, apps and reactions can be seen running (`running_behaviors`, the bridge's `current_*` tracking) and stopped, and a long-running verb holds its caller, as it would on the robot. The fast tier makes them instant; [testing.md](testing.md) "Instant fake behaviors" explains how.
- **Posture:** `go_to_posture` returns `posture_succeeds` (default `True`).
- **Joints:** `get_joints()` returns fixed `joint_names` / `joint_angles`.
- **Sensor events:** test helpers `touch(key, value)` and `emit_audio(channels, samples_per_channel, buffer)` call the subscribed callback the way Naoqi's threads would. With nothing subscribed they do nothing.
- **Paced audio:** Naoqi pushes buffers on its own, so the fake does too. While audio is subscribed, a thread pushes a silent mono chunk of `audio_chunk_s × 16000` samples every `audio_chunk_s` seconds (default 0.085). The push stops on `unsubscribe_audio()` / `close()`. Setting `audio_chunk_s` to `None` pauses it, so a test pushes only what it `emit_audio`s.

### Errors

`RobotConnectionError(RuntimeError)`: the robot couldn't be reached, or the real backend lacks `qi`. Other failures are Naoqi's own exceptions, raised unwrapped; the bridge catches them per verb.

## Open questions

1. **Simulated Naoqi.** A Choregraphe virtual robot is already reachable as `real` at `127.0.0.1:<port>`. A dedicated `sim` backend name only becomes useful if something needs to tell it apart (e.g. skipping hardware-only calls).
2. **Newer Naoqi / robots.** The slice is only verified on Naoqi 2.1.4.13 / Nao v5. Nao v6 or Pepper may need service calls adjusted inside `RealNaoRobot`; the Protocol shouldn't change.
