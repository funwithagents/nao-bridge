"""The ``fake`` backend: an offline ``NaoqiRobot`` that records every command.

Specified by [specs/robot.md](../../specs/robot.md). It serves a fixed ``packages2``-shaped
package list, simulates behavior runs, speech and posture moves that take time, and
sensor events, reports the joints of the posture it's in, pushes silent audio and
serves paced, deterministic camera frames.
"""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from .config import AudioChannel, CameraResolution
from .robot import (
    AUDIO_SAMPLE_RATE,
    AudioCallback,
    Camera,
    CameraRead,
    PostureCallback,
    PostureKey,
    RobotConnectionError,
    TouchCallback,
    TouchPart,
)

__all__ = [
    "CAMERA_SIZES",
    "FAKE_CAMERA_FOV",
    "FAKE_CAMERA_TRANSFORMS",
    "JOINT_NAMES",
    "POSTURE_ANGLES",
    "POSTURE_FAMILIES",
    "REST_POSTURE",
    "FakeNaoqiRobot",
    "fake_camera_pixels",
]


def _root_package(
    uuid: str, name_en: str, name_fr: str, description: str
) -> dict[str, Any]:
    """A package whose single behavior is its root (``path == "."``), in packages2 shape."""
    return {
        "uuid": uuid,
        "elems": {
            "names": {"en_US": name_en, "fr_FR": name_fr},
            "descriptions": {"en_US": description},
            "contents": {"behaviors": [{"path": ".", "langToTags": {}}]},
        },
    }


def _sub_behaviors_package(
    uuid: str,
    name_en: str,
    name_fr: str,
    description: str,
    behaviors: list[tuple[str, list[str]]],
) -> dict[str, Any]:
    """A package of sub-behaviors, each a ``(path, en_US tags)`` pair, in packages2 shape."""
    return {
        "uuid": uuid,
        "elems": {
            "names": {"en_US": name_en, "fr_FR": name_fr},
            "descriptions": {"en_US": description},
            "contents": {
                "behaviors": [
                    {
                        "path": path,
                        "langToName": {},
                        "langToDesc": {},
                        "langToTags": {"en_US": tags},
                    }
                    for path, tags in behaviors
                ]
            },
        },
    }


_FAKE_PACKAGES: list[dict[str, Any]] = [
    _root_package(
        "caravan-palace-se",
        "Electro Swing",
        "Electro Swing",
        "Nao dances on Electro Swing music.",
    ),
    _root_package(
        "eagle-dance",
        "Eagle Dance",
        "La danse de l'aigle",
        "This is a slow dance with impressive moves balanced on one foot.",
    ),
    _root_package(
        "gangnam-style", "Gangnam Style", "Gangnam Style", "Gangnam style dance."
    ),
    _root_package(
        "thriller-dance",
        "The thriller dance",
        "La danse thriller",
        "Nao dances on Michael Jackson's thriller.",
    ),
    _root_package(
        "follow-me",
        "Follow me",
        "Suis moi",
        "Nao gives you its hand and walks with you as long as its arm is raised.",
    ),
    _root_package(
        "presentation",
        "Presentation",
        "Présentation",
        "Nao speaks about itself and what it can be used for.",
    ),
    _root_package(
        "soccer-demonstration",
        "Soccer Demonstration",
        "Démo de foot",
        "Nao asks for a red ball, throws it, tracks it, walks to it and shoots.",
    ),
    _root_package(
        "walktotheball",
        "Walk to the ball",
        "Marche vers la balle",
        "Show a red ball to Nao and it walks towards it.",
    ),
    _root_package("boot-config", "Boot config", "Boot config", "System package."),
    _sub_behaviors_package(
        "animations",
        "Animations",
        "Animations",
        "Emotional and expressive animations, standing and sitting.",
        [
            ("Stand/Emotions/Positive/Happy_1", ["happy"]),
            ("Stand/Emotions/Positive/Happy_2", ["happy"]),
            ("Stand/Emotions/Positive/Proud_1", ["proud"]),
            ("Stand/Emotions/Positive/Laugh_1", ["laugh"]),
            ("Stand/Emotions/Negative/Sad_1", ["sad"]),
            ("Sit/Emotions/Positive/Happy_1", ["happy"]),
        ],
    ),
    _sub_behaviors_package(
        "dialog_touch",
        "Touch dialog",
        "Dialogue tactile",
        "Nao reacts when its head is touched.",
        [("animations/head_touched", [])],
    ),
    _sub_behaviors_package(
        "dialog_move_arms",
        "Move arms dialog",
        "Dialogue bouger les bras",
        "Nao raises or stretches one or both arms.",
        [
            ("animations/StretchBothArms", []),
            ("animations/StretchLArm", []),
            ("animations/StretchRArm", []),
            ("animations/UpBothArms", []),
            ("animations/UpLArm", []),
            ("animations/UpRArm", []),
        ],
    ),
]

# The postures the fake can be in, as joint angles (radians), one row per joint in
# Naoqi's ``getBodyNames("Body")`` order. Measured on a simulated Nao (naoqi-sim):
# each posture reached with ``ALRobotPosture``, then read with ``get_joints()``.
_POSTURE_TABLE: list[tuple[str, float, float, float]] = [
    # joint, Crouch, Stand, Sit
    ("HeadYaw", 0.00, 0.00, -0.03),
    ("HeadPitch", 0.10, -0.17, -0.04),
    ("LShoulderPitch", 1.41, 1.47, 0.88),
    ("LShoulderRoll", 0.19, 0.18, 0.25),
    ("LElbowYaw", -0.80, -1.19, -0.45),
    ("LElbowRoll", -1.06, -0.42, -1.21),
    ("LWristYaw", 0.15, 0.10, 0.04),
    ("LHand", 0.00, 0.30, 0.30),
    ("LHipYawPitch", -0.25, -0.17, -0.62),
    ("LHipRoll", -0.08, 0.10, 0.28),
    ("LHipPitch", -0.70, 0.13, -1.54),
    ("LKneePitch", 2.11, -0.09, 1.40),
    ("LAnklePitch", -1.18, 0.09, 0.84),
    ("LAnkleRoll", 0.08, -0.13, -0.01),
    ("RHipYawPitch", -0.25, -0.17, -0.62),
    ("RHipRoll", 0.08, -0.10, -0.27),
    ("RHipPitch", -0.70, 0.13, -1.54),
    ("RKneePitch", 2.11, -0.09, 1.41),
    ("RAnklePitch", -1.18, 0.09, 0.85),
    ("RAnkleRoll", -0.08, 0.13, 0.02),
    ("RShoulderPitch", 1.41, 1.47, 0.94),
    ("RShoulderRoll", -0.19, -0.18, -0.29),
    ("RElbowYaw", 0.80, 1.19, 0.51),
    ("RElbowRoll", 1.06, 0.42, 1.25),
    ("RWristYaw", -0.15, 0.10, -0.03),
    ("RHand", 0.00, 0.30, 0.30),
]
JOINT_NAMES = tuple(row[0] for row in _POSTURE_TABLE)
POSTURE_ANGLES: dict[str, tuple[float, ...]] = {
    "Crouch": tuple(crouch for _, crouch, _, _ in _POSTURE_TABLE),
    "Stand": tuple(stand for _, _, stand, _ in _POSTURE_TABLE),
    "Sit": tuple(sit for _, _, _, sit in _POSTURE_TABLE),
}
# Where a robot is when it starts and after rest(): Naoqi's rest posture on a Nao.
REST_POSTURE = "Crouch"
# Each posture's family, as ALRobotPosture.getPostureFamily() reports it on a Nao
# with NAOqi 2.1 (2.8 calls Crouch's family "Crouching").
POSTURE_FAMILIES: dict[str, str] = {
    "Crouch": "Standing",
    "Stand": "Standing",
    "Sit": "Sitting",
}

# (width, height) per resolution, as ALVideoDevice serves them.
CAMERA_SIZES: dict[CameraResolution, tuple[int, int]] = {
    "qqvga": (160, 120),
    "qvga": (320, 240),
    "vga": (640, 480),
    "4vga": (1280, 960),
}
# A Nao v5 camera's (horizontal, vertical) field of view, radians.
FAKE_CAMERA_FOV = (1.063, 0.831)
# Each camera's pose in FRAME_ROBOT (row-major 4x4), measured on a simulated Nao
# (naoqi-sim 2.1) at Crouch, as for the joint angles above.
FAKE_CAMERA_TRANSFORMS: dict[Camera, tuple[float, ...]] = {
    "top": (
        0.9975, -0.0001, 0.0711, 0.0621,
        0.0019, 0.9997, -0.0254, -0.0106,
        -0.0711, 0.0255, 0.9971, 0.4143,
        0.0, 0.0, 0.0, 1.0,
    ),
    "bottom": (
        0.7363, -0.0001, 0.6766, 0.0518,
        0.0173, 0.9997, -0.0187, -0.0094,
        -0.6764, 0.0255, 0.7361, 0.3689,
        0.0, 0.0, 0.0, 1.0,
    ),
}  # fmt: skip


def fake_camera_pixels(width: int, height: int, index: int) -> bytes:
    """The fake's BGR image for frame ``index``: a horizontal ramp on blue, the frame
    index modulo 256 on green, no red."""
    green = index % 256
    row = bytes(
        b for x in range(width) for b in (x * 255 // max(width - 1, 1), green, 0)
    )
    return row * height


@dataclass
class _FakeCamera:
    """A subscribed camera: the frame it serves until its period is up."""

    width: int
    height: int
    fps: int
    frame: CameraRead
    index: int
    served_at: float  # time.monotonic() when ``frame`` became current


class FakeNaoqiRobot:
    """Offline ``NaoqiRobot``: records commands, serves a fixed package list.

    Tests reach it through ``bridge.robot`` to assert on ``commands``, tune
    ``behavior_duration_s`` / ``speech_duration_s`` / ``posture_duration_s`` /
    ``posture_succeeds`` / ``awake`` / ``posture``, and fire sensor events with
    ``touch`` / ``posture_event`` / ``emit_audio``. A subscribed posture callback hears
    every change of ``posture`` made by ``rest()`` or a completed move, as Naoqi's
    posture events. ``get_joints()`` reports the angles of ``posture``,
    which starts at ``REST_POSTURE`` and follows ``rest()`` and completed
    ``go_to_posture`` moves; ``wake_up()`` keeps it, as on a Nao. While audio is subscribed, a thread pushes a silent
    mono chunk every ``audio_chunk_s`` seconds, as Naoqi pushes its buffers; setting
    ``audio_chunk_s`` to ``None`` pauses it, so a test pushes only what it emits.
    A subscribed camera serves a new frame every ``camera_period_s`` seconds (the
    subscribed ``1 / fps`` while it is ``"fps"``) and the same one in between, as
    Naoqi does; ``None`` freezes every camera on its current frame.
    """

    # How long a behavior runs unless stopped: long enough to be seen running and
    # stopped, as on a robot. The fast tier sets it to 0 (tests/conftest.py).
    DEFAULT_BEHAVIOR_DURATION_S = 5.0
    # Likewise for a ``say`` and a posture move, so a cancel can be seen stopping them.
    DEFAULT_SPEECH_DURATION_S = 1.0
    DEFAULT_POSTURE_DURATION_S = 2.0

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.connected = False
        self.awake = False  # motors at rest, as a robot starts
        self.behavior_duration_s = self.DEFAULT_BEHAVIOR_DURATION_S
        self.speech_duration_s = self.DEFAULT_SPEECH_DURATION_S
        self.posture_duration_s = self.DEFAULT_POSTURE_DURATION_S
        self.posture_succeeds = True
        self.posture = REST_POSTURE
        self._running: dict[str, threading.Event] = {}
        self._speeches: set[threading.Event] = set()
        self._posture_moves: set[threading.Event] = set()
        self._lock = threading.Lock()
        self._touch_callback: TouchCallback | None = None
        self._posture_callback: PostureCallback | None = None
        self._audio_callback: AudioCallback | None = None
        self.audio_chunk_s: float | None = 0.085
        self._audio_stop = threading.Event()
        self._audio_thread: threading.Thread | None = None
        self.camera_period_s: float | None | Literal["fps"] = "fps"
        self._cameras: dict[Camera, _FakeCamera] = {}

    def _record(self, method: str, **args: Any) -> None:
        self.commands.append((method, args))

    def _wait_unless_ended(
        self, pending: set[threading.Event], duration: float
    ) -> bool:
        """Block for ``duration`` s, or until ``_end_all(pending)`` ends the wait;
        ``True`` when it was ended early."""
        ended = threading.Event()
        with self._lock:
            pending.add(ended)
        try:
            return ended.wait(duration)
        finally:
            with self._lock:
                pending.discard(ended)

    def _end_all(self, pending: set[threading.Event]) -> None:
        """End every wait in ``pending``; over once this returns, as on the robot."""
        with self._lock:
            waits = list(pending)
            pending.clear()
        for ended in waits:
            ended.set()

    @property
    def running_behaviors(self) -> list[str]:
        with self._lock:
            return list(self._running)

    @property
    def speaking(self) -> bool:
        with self._lock:
            return bool(self._speeches)

    @property
    def moving_posture(self) -> bool:
        with self._lock:
            return bool(self._posture_moves)

    def connect(self, cancel: threading.Event | None = None) -> None:
        if cancel is not None and cancel.is_set():
            raise RobotConnectionError("connection cancelled")
        self._record("connect")
        self.connected = True

    def close(self) -> None:
        self._record("close")
        self.connected = False
        self._stop_audio_push()
        with self._lock:
            self._cameras.clear()
        with self._lock:  # over once this returns, as on the robot
            for stop in self._running.values():
                stop.set()
            self._running.clear()
        self._end_all(self._speeches)
        self._end_all(self._posture_moves)

    def set_language(self, language: str) -> None:
        self._record("set_language", language=language)

    def say(self, text: str) -> None:
        self._record("say", text=text)
        self._wait_unless_ended(self._speeches, self.speech_duration_s)

    def stop_speech(self) -> None:
        self._record("stop_speech")
        self._end_all(self._speeches)

    def wake_up(self) -> None:
        self._record("wake_up")
        self.awake = True

    def rest(self) -> None:
        self._record("rest")
        self.awake = False
        self._settle_in(REST_POSTURE)

    def is_awake(self) -> bool:
        return self.awake

    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool:
        self._record("go_to_posture", posture=posture, speed=speed, max_tries=max_tries)
        stopped = self._wait_unless_ended(self._posture_moves, self.posture_duration_s)
        if self.posture_succeeds and not stopped and posture in POSTURE_ANGLES:
            self._settle_in(posture)
        return self.posture_succeeds

    def stop_posture(self) -> None:
        self._record("stop_posture")
        self._end_all(self._posture_moves)

    def _settle_in(self, posture: str) -> None:
        """Be in ``posture``, and report the change the way Naoqi's events do."""
        before = self.posture
        self.posture = posture
        if posture == before:
            return
        self.posture_event("PostureChanged", posture)
        family = POSTURE_FAMILIES[posture]
        if family != POSTURE_FAMILIES[before]:
            self.posture_event("PostureFamilyChanged", family)

    def get_posture(self) -> tuple[str, str]:
        return self.posture, POSTURE_FAMILIES[self.posture]

    def subscribe_posture(self, callback: PostureCallback) -> None:
        self._record("subscribe_posture")
        self._posture_callback = callback

    def unsubscribe_posture(self) -> None:
        self._record("unsubscribe_posture")
        self._posture_callback = None

    def set_breathing(self, chain_name: str, enabled: bool) -> None:
        self._record("set_breathing", chain_name=chain_name, enabled=enabled)

    def fade_eyes(self, color: str) -> None:
        self._record("fade_eyes", color=color)

    def set_basic_awareness(
        self, enabled: bool, engagement_mode: str, tracking_mode: str
    ) -> None:
        self._record(
            "set_basic_awareness",
            enabled=enabled,
            engagement_mode=engagement_mode,
            tracking_mode=tracking_mode,
        )

    def list_packages(self) -> list[dict[str, Any]]:
        return copy.deepcopy(_FAKE_PACKAGES)

    def run_behavior(self, name: str) -> None:
        stop = threading.Event()
        with self._lock:
            self._running[name] = stop
        self._record("run_behavior", name=name)
        try:
            stop.wait(self.behavior_duration_s)
        finally:
            with self._lock:
                if self._running.get(name) is stop:
                    del self._running[name]

    def stop_behavior(self, name: str) -> None:
        self._record("stop_behavior", name=name)
        with self._lock:  # over once this returns, as on the robot
            stop = self._running.pop(name, None)
        if stop is not None:
            stop.set()

    def get_joints(self) -> tuple[list[str], list[float]]:
        return list(JOINT_NAMES), list(POSTURE_ANGLES[self.posture])

    def subscribe_touch(self, callback: TouchCallback) -> None:
        self._record("subscribe_touch")
        self._touch_callback = callback

    def unsubscribe_touch(self) -> None:
        self._record("unsubscribe_touch")
        self._touch_callback = None

    def subscribe_audio(self, callback: AudioCallback, channel: AudioChannel) -> None:
        self._record("subscribe_audio", channel=channel)
        self._audio_callback = callback
        self._audio_stop.clear()
        self._audio_thread = threading.Thread(
            target=self._push_audio, name="fake-naoqi-audio", daemon=True
        )
        self._audio_thread.start()

    def unsubscribe_audio(self) -> None:
        self._record("unsubscribe_audio")
        self._stop_audio_push()
        self._audio_callback = None

    def _stop_audio_push(self) -> None:
        self._audio_stop.set()
        thread, self._audio_thread = self._audio_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _push_audio(self) -> None:
        while not self._audio_stop.is_set():
            period = self.audio_chunk_s
            if period is None:
                self._audio_stop.wait(0.01)
                continue
            if self._audio_stop.wait(period):
                return
            samples = round(period * AUDIO_SAMPLE_RATE)
            callback = self._audio_callback
            if callback is not None:
                callback(1, samples, bytes(2 * samples))

    def subscribe_camera(
        self, camera: Camera, resolution: CameraResolution, fps: int
    ) -> None:
        self._record("subscribe_camera", camera=camera, resolution=resolution, fps=fps)
        width, height = CAMERA_SIZES[resolution]
        with self._lock:
            self._cameras[camera] = _FakeCamera(
                width,
                height,
                fps,
                self._camera_frame(camera, width, height, 0, 0.0),
                0,
                time.monotonic(),
            )

    def read_camera(self, camera: Camera) -> CameraRead | None:
        if not self.connected:
            raise RobotConnectionError("not connected")
        with self._lock:
            state = self._cameras.get(camera)
            if state is None:
                raise RuntimeError(f"the {camera} camera is not subscribed")
            period = self.camera_period_s
            if period == "fps":
                period = 1.0 / state.fps
            now = time.monotonic()
            if period is not None and now - state.served_at >= period:
                state.index += 1
                state.served_at = now
                state.frame = self._camera_frame(
                    camera,
                    state.width,
                    state.height,
                    state.index,
                    state.frame.naoqi_ts + period,
                )
            return state.frame

    def unsubscribe_camera(self, camera: Camera) -> None:
        self._record("unsubscribe_camera", camera=camera)
        with self._lock:
            self._cameras.pop(camera, None)

    @staticmethod
    def _camera_frame(
        camera: Camera, width: int, height: int, index: int, naoqi_ts: float
    ) -> CameraRead:
        return CameraRead(
            width=width,
            height=height,
            data=fake_camera_pixels(width, height, index),
            naoqi_ts=naoqi_ts,
            fov=FAKE_CAMERA_FOV,
            transform=FAKE_CAMERA_TRANSFORMS[camera],
        )

    def touch(self, key: TouchPart, value: float) -> None:
        """Simulate a tactile sensor event, as Naoqi would fire it."""
        if self._touch_callback is not None:
            self._touch_callback(key, value)

    def posture_event(self, key: PostureKey, value: str) -> None:
        """Simulate a posture event, as Naoqi would fire it (a fall, a push); leaves
        ``posture`` as it is."""
        if self._posture_callback is not None:
            self._posture_callback(key, value)

    def emit_audio(
        self, channels: int, samples_per_channel: int, buffer: bytes
    ) -> None:
        """Simulate a microphone buffer, as Naoqi would push it."""
        if self._audio_callback is not None:
            self._audio_callback(channels, samples_per_channel, buffer)
