---
code:
  - src/naoqi_bridge/camera.py
  - src/naoqi_bridge/bridge.py
  - src/naoqi_bridge/config.py
  - src/naoqi_bridge/robot.py
  - src/naoqi_bridge/real_robot.py
  - src/naoqi_bridge/fake_robot.py
  - src/naoqi_bridge/naoqi_websocket_server.py
  - pyproject.toml
tests:
  - tests/test_camera.py
  - tests/test_bridge.py
  - tests/test_config.py
  - tests-e2e/test_live_streams.py
---

# Camera feeds — one reader per robot camera (`camera.py`)

**Status:** Implemented

## Purpose

The bridge's video input: **one reader per camera** (Nao has two, top and bottom), running for the session, publishing the newest frame together with **where the camera was** when the frame was read, for any number of consumers to sample or follow at their own pace: the WebSocket server's `Frame` stream, a display, a detector, a vision graph built with another library. `bridge.cameras["top"]` and `bridge.cameras["bottom"]` are those feeds.

The design follows the mic feed ([microphone.md](microphone.md)) in lifecycle and the joints stream ([observable.md](observable.md)) in shape: a frame is a **state where only the latest matters**, not a signal every consumer needs whole. A consumer slower than the camera sees fewer frames and never falls behind; a consumer faster than it sees the same frame again and tells by `frame_id`.

### Why one feed per camera, pulled

Unlike `ALAudioDevice`, which pushes buffers to a registered service, **`ALVideoDevice` is pull-based** for a remote client: `subscribeCamera(name, camera, resolution, colorspace, fps)` returns a handle, `getImageRemote(handle)` returns the newest frame for that handle (the *same* frame again, with the same timestamp, until a new one is captured), and `unsubscribe(handle)` ends it. Naoqi converts per subscriber, on the robot: each subscription costs the robot's CPU and, on Wi-Fi, its own stream. Measured through qi 3.1.8 on a naoqi-sim 2.1 (one pull):

| Resolution (BGR) | `getImageRemote` median | Bytes per frame |
|---|---|---|
| QVGA 320×240 | 0.9 ms | 230 400 |
| VGA 640×480 | 1.8 ms | 921 600 |
| 4VGA 1280×960 | 3.9 ms | 3 686 400 |

So the bridge opens **exactly one subscription per enabled camera**, at the resolution and rate the config says, and pulls it from one bridge task per camera. Every consumer gets that camera's frames at that resolution; one that wants less downsizes its copy. Several subscriptions on one camera (one per consumer resolution) are deliberately not offered: they would multiply the robot's conversion work and the Wi-Fi traffic, bring runtime subscription lifecycles into the bridge, and break the rule that the config says what the bridge pulls ([config.md](config.md) "Streams").

## Core concepts / Decided

### The cameras

```python
type Camera = Literal["top", "bottom"]
```

Naoqi's `CameraTop` (index 0, looking ahead) and `CameraBottom` (index 1, tilted about 40° down, at the feet and the table in front). Each has its own config block, feed, subscription and task; one can run without the other, at its own resolution and rate. The seam keeps Naoqi's names and codes ([robot.md](robot.md)); the bridge speaks `"top"` / `"bottom"`.

### The frame

```python
@dataclass(frozen=True)
class CameraFrame:
    frame_id: int                      # 1, 2, 3, … per feed — the key a result is matched on
    ts: float                          # time.monotonic() when the bridge received the frame
    camera: Camera
    width: int
    height: int
    data: bytes                        # BGR, 3 bytes per pixel, row-major — Naoqi's buffer, as is
    naoqi_ts: float                    # Naoqi's capture timestamp, seconds on the robot's clock
    camera_transform: tuple[float, ...]  # 16 floats, a row-major 4×4: camera → FRAME_ROBOT, read with the frame
    fov: tuple[float, float]           # the camera's horizontal and vertical field of view, radians

    @property
    def image(self) -> npt.NDArray[np.uint8]: ...  # (height, width, 3) BGR, a zero-copy view of data
```

- **`frame_id`** increases by one per published frame, from 1, and keeps counting across sessions of the same bridge object, so a result from an earlier session can never be mistaken for a new one. `published_count` equals the last `frame_id`; the achieved rate over a window is `Δpublished_count / Δt`.
- **`ts`** is the arrival time on the bridge's monotonic clock, as for `MicChunk` and `JointsState`. **`naoqi_ts`** is the timestamp Naoqi set when the frame was captured (the image's `timestamp_s + timestamp_us / 1e6`): epoch time on NAOqi 2.1, the robot's monotonic clock on 2.8, so it orders and tells frames apart but is never compared with `ts`. It is the key the feed uses to publish a frame once.
- **`data`** is Naoqi's buffer copied once into `bytes`, shared by reference with every consumer; `bytes` is immutable, so no consumer can alter what another reads. The colorspace is **BGR** (`kBGRColorSpace`, 13), the convention of OpenCV and of the vision libraries a frame is handed to; a consumer that wants RGB flips its copy.
- **`image`** builds a `numpy` view on `data` (`np.frombuffer(...).reshape(height, width, 3)`, read-only), so a frame costs nothing until a consumer asks for the array, and a consumer that only wants the bytes (a JPEG encoder) never touches numpy. `frame_id`, `ts` and `image` are the names a vision graph built on latest-value sampling reads (the `Upstream[FrameLike]` shape of the funwithagents vision-modules runtime): `CameraFeed.latest()` returning `CameraFrame`s plugs onto one without an adapter. The compatibility is structural; the bridge imports no vision library.
- **`camera_transform`** is `ALMotion.getTransform(<camera>, FRAME_ROBOT, True)` read **right after the image**, in the same seam call (0.2 ms; image and transform together are 0.8 ms at QVGA on the sim). FRAME_ROBOT is Naoqi's frame on the ground between the feet, x forward, y left, z up: the frame `ALTracker.lookAt` / `pointAt`, `ALMotion.moveTo`, people perception and sound localization all take, where FRAME_TORSO tilts with the body and FRAME_WORLD drifts with odometry. In the camera's own frame x is the optical axis, y left, z up. The transform is read at the pull, not at the capture: the frame is up to one period old (plus the network), so while the head turns fast the pose can be a few degrees off. Open question 1 says how to tighten it; the spec says it plainly rather than attach a pose it can't stand behind.
- **`fov`** is `(left − right, top − bottom)` of the angles Naoqi returns with every image: `(1.063, 0.831)` rad, 60.9° × 47.6°, for a Nao v5 camera. With it a consumer maps a pixel to a direction in the camera frame without a calibration file: for a point at normalised `(u, v)` (origin top-left), `yaw = (0.5 − u) · fov[0]`, `pitch = (v − 0.5) · fov[1]` (positive down, as Naoqi's `getAngularPositionFromImagePosition` reports), direction `(cos pitch · cos yaw, cos pitch · sin yaw, −sin pitch)`; through `camera_transform` that is a ray in FRAME_ROBOT, and a point along it at an assumed distance is what gaze needs (open question 2).

### The feed

```
CameraFeed(camera)
  .camera -> Camera
  async .start(robot, settings) / async .stop()   # the bridge's to call (lifecycle below)
  .latest() -> CameraFrame | None                 # the newest frame; None before the first / outside a session
  .published_count -> int                         # frames published, ever, on this feed
  .frames() -> AsyncIterator[CameraFrame]         # latest-wins; ends with the session
  async .wait_for(predicate) -> CameraFrame       # the first frame, from now, that satisfies predicate
```

- **A bridge task per feed, like the joints task.** `start()` subscribes the camera on the robot (`robot.subscribe_camera(camera, resolution, fps)`, off the loop) and spawns the task. Every `1 / fps` seconds the task calls `robot.read_camera(camera)` in `asyncio.to_thread` and, when the read's `naoqi_ts` differs from the last published one, stamps a `CameraFrame` (`frame_id`, `ts`) and publishes it. A read with the same `naoqi_ts` is Naoqi handing the last frame again: nothing is published, the period waits on. The task paces on the loop's clock from the task's start, so the pull rate never exceeds `fps` and a slow read shortens the next wait rather than drifting.
- **Latest value, published through an `Observable`.** Inside, the feed holds an `Observable[CameraFrame | None]` ([observable.md](observable.md)), `set` on the loop. `latest()` is its `value`, read instantly from any thread. `frames()` iterates its `changes()`: a subscriber that keeps up sees every published frame, one that doesn't gets the newest, and nothing ever blocks the task or another subscriber. `frames()` returns when the session stops (the feed publishes `None`, which `frames()` consumes and ends on); it never carries over into a later session. `wait_for` is the observable's, over frames only (the newest frame if it matches, else the first published one that does), and raises `NotRunningError` if the session stops first.
- **Checks at the call:** `frames()` and `wait_for` on a feed whose camera is disabled in the config raise `BridgeError`, and on a bridge that isn't running `NotRunningError`, where they are called, not at the first `async for` — the rules of `audio_input()`. `latest()` never raises: it is `None` for a disabled camera and outside a session.
- **Failures.** A `read_camera` that raises is logged at `DEBUG` and retried at the next period; one that keeps raising for `CAMERA_DOWN_S = 5` s logs one `WARNING` (and one `INFO` when frames return), and the last frame stays published meanwhile. A camera whose `naoqi_ts` **never changes** for `CAMERA_DOWN_S` logs one `WARNING` naming the camera: that is a camera Naoqi serves but nothing feeds, which is what a naoqi-sim's bottom camera is today ([sim.md](sim.md); it answers a constant placeholder with timestamp 0). The feed does not fail the session for it.
- **Bound per session, alive per bridge.** `bridge.cameras` is a read-only mapping holding **both** feeds from construction, enabled or not, so a consumer wires itself to a feed before the session starts. `NaoqiBridge.start()` starts each feed whose `streams.cameras.<camera>.enabled` is set, after the mic feed; `stop()` stops them before the mic feed. `stop()` cancels the task, publishes `None` (so `latest()` reads `None` and every `frames()` ends), and unsubscribes the camera on the robot, off the loop. Cancelling `start()` tears the feeds down with the rest ([bridge.md](bridge.md) "Lifecycle").
- **Stale handles.** Naoqi keeps a remote subscription until it is unsubscribed or the robot reboots, allows **seven** handles per subscriber name (`name_0` … `name_6`; the eighth `subscribeCamera` returns an empty handle), and answers `False`, not an error, to `unsubscribe` of an unknown handle. A bridge process that died without unsubscribing therefore leaves a handle behind, and seven such deaths would exhaust the name. So `subscribe_camera` first unsubscribes `<name>_0` … `<name>_6` for its camera's name, then subscribes. The names are `NaoqiBridgeCameraTop` and `NaoqiBridgeCameraBottom`.

### Config: `streams.cameras`

```json
"streams": {
  "cameras": {
    "top":    { "enabled": true,  "resolution": "qvga", "fps": 10 },
    "bottom": { "enabled": false, "resolution": "qvga", "fps": 10 }
  }
}
```

```python
type CameraResolution = Literal["qqvga", "qvga", "vga", "4vga"]

@dataclass
class CameraStream(JsonConfig):
    enabled: bool = False
    resolution: CameraResolution = "qvga"
    fps: int = 10                      # an integer, 1 to 30

@dataclass
class CameraStreams(JsonConfig):
    top: CameraStream = field(default_factory=CameraStream)
    bottom: CameraStream = field(default_factory=CameraStream)
```

| `resolution` | Size | Naoqi code | Note |
|---|---|---|---|
| `qqvga` | 160×120 | 0 | |
| `qvga` | 320×240 | 1 | the default: 2.3 MB/s of BGR at 10 fps, what Wi-Fi carries comfortably |
| `vga` | 640×480 | 2 | the largest a naoqi-sim serves (2.8's `putImage` stops at VGA) |
| `4vga` | 1280×960 | 3 | a Nao v5's top camera; **a NAOqi 2.8 sim silently serves QVGA for it**. The frame says its real `width` × `height`; the config is a request |

`fps` is the rate asked of Naoqi (`subscribeCamera`'s last argument; Naoqi refreshes the subscriber's frame at most that often) and the feed's pull period. Both are checked at load: an unknown `resolution` and an `fps` that isn't an integer in 1–30 are `ConfigError`s naming `streams.cameras.<camera>.<field>`. Colorspace is not configurable (BGR, above). The default config enables no camera, as for the other streams.

### The seam ([robot.md](robot.md))

```python
@dataclass(frozen=True)
class CameraRead:                      # what one pull returns, in Naoqi's terms
    width: int
    height: int
    data: bytes                        # BGR
    naoqi_ts: float
    fov: tuple[float, float]           # (left − right, top − bottom) angles, radians
    transform: tuple[float, ...]       # ALMotion.getTransform(<camera>, FRAME_ROBOT, True), 16 floats

class NaoqiRobot(Protocol):
    def subscribe_camera(self, camera: Camera, resolution: CameraResolution, fps: int) -> None: ...
    def read_camera(self, camera: Camera) -> CameraRead | None: ...   # None: Naoqi returned no image
    def unsubscribe_camera(self, camera: Camera) -> None: ...
```

- `RealNaoqiRobot`: `subscribe_camera` clears the stale handles (above), then `ALVideoDevice.subscribeCamera(name, index, resolution_code, 13, fps)` and keeps the handle per camera. `read_camera` is `getImageRemote(handle)`, then `ALMotion.getTransform(camera_name, 2, True)`, then `releaseImage(handle)`; it builds `CameraRead` from the image's `width, height, …, timestamp_s, timestamp_us, buffer, …, left, top, right, bottom`. `unsubscribe_camera` is `unsubscribe(handle)` and forgets it; `close()` unsubscribes what is still subscribed. The constants (`CAMERA_INDEXES`, `CAMERA_NAMES`, `CAMERA_RESOLUTION_CODES`, `CAMERA_SUBSCRIBER_NAMES`, the BGR code, `FRAME_ROBOT`) live in `robot.py` with the audio ones.
- The two Naoqi calls of a read run back to back on the same thread; the transform is the camera's pose within a millisecond of the pull.

### Consumers in this repo

- **WebSocket server** ([naoqi-websocket-server.md](naoqi-websocket-server.md)): for each enabled camera, a task per client session follows `frames()` and sends a `Frame` message per frame it gets, `{camera, frameId, width, height, format: "jpeg", data: base64, cameraTransform: [16 floats], fov: [h, v]}`. The frame is JPEG-encoded with Pillow off the loop (`asyncio.to_thread`, quality 80; QVGA comes to 10–20 KB, about 150 KB/s at 10 fps), and `frames()` is latest-wins, so a slow connection or a slow encode skips frames rather than lagging. Like audio, the stream is on whenever the bridge config enables the camera (open question 5).
- **A Python caller**: `bridge.cameras["top"].latest()` for a picture now, `async for frame in bridge.cameras["top"].frames()` to react to each one.

### Dependencies

`numpy` and `Pillow` become **runtime dependencies** ([project.md](project.md)): numpy for `CameraFrame.image`, Pillow for the WebSocket server's JPEG encoding, which the standard library can't do. No `[camera]` extra: both have wheels on every platform (the fake-only ones included), and they are modest (installed on macOS arm64: numpy 22 MB, Pillow 13 MB; OpenCV, which isn't needed, would be several times that). `camera.py` and the WebSocket server import them **lazily**, inside the `image` property and the encoder, so importing `naoqi_bridge` or running a fake session with no camera pays no import. The mic feed's "no conversion, no numpy in its path" stands ([microphone.md](microphone.md)).

### `fake` backend support

`FakeNaoqiRobot` ([robot.md](robot.md)) serves frames the way Naoqi does: `subscribe_camera` records the call and the settings; `read_camera` returns a `CameraRead` at the subscribed size, a new one every `1 / fps` seconds (`naoqi_ts` advancing by the period, from 0) and the **same one again** in between, as `getImageRemote` does; `unsubscribe_camera` records and forgets. The image is deterministic and differs frame to frame: a horizontal ramp on the blue channel and the frame index modulo 256 on the green one, so tests assert structure and freshness, not motion. `fov` is the Nao v5 pair above and `transform` a fixed camera-to-robot matrix per camera, measured on a simulated Nao at `Crouch` (`FAKE_CAMERA_TRANSFORMS`). `camera_period_s: float | None` overrides the pacing like `audio_chunk_s` does for audio; `None` freezes the frame, so a test sees the "same `naoqi_ts`, nothing published" rule. Reads are not recorded in `commands`, like `get_joints()`.

`tests/` check on the fake:
- a feed publishes every new frame in order, `frame_id` from 1, `published_count` equal to it, and nothing while the fake repeats a frame;
- `latest()` is `None` before `start()` and after `stop()`, and `frame_id` counts on across a restart;
- two `frames()` subscribers both see every frame at the fake's rate, and a slow one gets the newest, not a backlog;
- `frames()` ends when the session stops; a cancelled subscriber leaves the others running;
- `frames()` on a disabled camera raises `BridgeError`, on a stopped bridge `NotRunningError`; `latest()` on a disabled camera is `None`;
- a `read_camera` that raises keeps the last frame and the feed recovers; one failing past a shortened `CAMERA_DOWN_S` warns once;
- `image` is a `(height, width, 3)` `uint8` view whose bytes are `data`; `fov` and `camera_transform` are what the fake served;
- the config: defaults, the two blocks, `resolution` and `fps` checks with their key paths;
- the bridge subscribes exactly the enabled cameras with the configured settings, and unsubscribes them at `stop()`;
- the WebSocket session sends a decodable JPEG `Frame` per published frame with the right `camera` and size.

### Live tier ([testing.md](testing.md))

A test gated on `camera` enables the top camera at `qvga`, 10 fps, waits up to 3 s for `latest()`, and asserts the frame is 320×240 with `len(data) == width × height × 3`, that `camera_transform` is a plausible pose (last row `0 0 0 1`, the camera between 0.3 and 0.6 m above the ground, since the robot is sitting or standing), and that at least 5 frames arrive in the next second; it records the measured rate in the run's `measured live` summary. The `camera` capability already exists and the `sim` profile pins it ([testing_support.md](testing_support.md)): naoqi-sim renders the top camera at 15 fps into `ALVideoDevice`, so the test runs on every CI run. The bottom camera has no live test until naoqi-sim feeds it (open question 3).

## Relationship to the other specs

- **[config.md](config.md):** the `streams.cameras` block; `CameraStream`, `CameraStreams`, `CameraResolution`.
- **[bridge.md](bridge.md):** `bridge.cameras`; the feeds' place in `start()` / `stop()`; `CameraFrame` and `Camera` exported from the front door.
- **[robot.md](robot.md):** `subscribe_camera` / `read_camera` / `unsubscribe_camera`, `CameraRead`, the camera constants; the fake's paced frames.
- **[observable.md](observable.md):** the feed publishes through an `Observable`, on the loop.
- **[microphone.md](microphone.md):** the sibling feed; the ring is for a signal, the observable for a state.
- **[naoqi-websocket-server.md](naoqi-websocket-server.md):** the `Frame` message.
- **[sim.md](sim.md):** a sim feeds `CameraTop` only, at naoqi-sim's `video_input.fps`.
- **[project.md](project.md):** numpy and Pillow as runtime dependencies.
- **[testing.md](testing.md), [testing_support.md](testing_support.md):** the live camera test, gated on `camera`.

## Open questions

1. **The transform at capture time.** The frame's `camera_transform` is read at the pull, within a millisecond, but the capture was up to a period earlier. Naoqi has no "transform at time t", so the fix is the bridge's: a task sampling the camera transforms at a steady rate into a short history, and the feed interpolating at `naoqi_ts` (mapped once onto the bridge's clock from the first frame's pair of stamps). Deferred until a consumer measures the error as a problem; a consumer that needs it exactly can hold the head still for the shot.
2. **Looking at a pixel.** `ALTracker.lookAt([x, y, z], FRAME_ROBOT, speed, whole_body)` turns the head to a point, verified on the sim (a point at `[1, 0.5, 0.5]` gave yaw 0.47 rad). A `look_at(x, y, z)` verb, or `look_at_pixel(frame, u, v)` doing the ray maths of "The frame" with the frame's own transform, is the natural next step and deliberately not in this spec.
3. **The bottom camera on a sim.** naoqi-sim renders `CameraTop` only; `CameraBottom` answers a constant placeholder with timestamp 0 (the feed warns once). Rendering the bottom camera is naoqi-sim's open question 1; the bridge needs no change when it lands, and the live tier gains a bottom-camera test then.
4. **Colorspace.** BGR costs the robot one conversion per frame from its native YUV422. Asking for YUV422 and converting on the host would spare the Nao's CPU at the price of a conversion in the bridge; deferred until a robot shows the need.
5. **Which streams a server sends.** Today every stream the bridge config enables is streamed to the WebSocket client, as audio is. A server-side list of what to send (so one bridge config serves a client that wants the frames and another that doesn't) is a WebSocket-server concern, recorded there ([naoqi-websocket-server.md](naoqi-websocket-server.md) open questions).
6. **Several resolutions on one camera.** Rejected for now ("Why one feed per camera, pulled"); if a consumer needs the full 4VGA still beside a QVGA stream, a second subscription on the same camera, requested at runtime and counted against the seven handles, would be the shape.
7. **The cameras over MCP.** The MCP server exposes no camera yet. Whether an agent gets a picture tool, and in what shape (the frame as an image content, which camera, what an LLM client does with it), is deferred until the agent use case is clearer ([naoqi-mcp-server.md](naoqi-mcp-server.md)).
