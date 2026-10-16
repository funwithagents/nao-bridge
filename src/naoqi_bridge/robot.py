"""Connection seam between naoqi-bridge and a Naoqi robot.

Specified by [specs/robot.md](../../specs/robot.md). ``NaoqiRobot`` is the Protocol listing
the Naoqi capabilities the bridge consumes, with the types and constants both
implementations share. ``RealNaoqiRobot`` ([real_robot.py](real_robot.py)) implements it
over a ``qi`` session and ``FakeNaoqiRobot`` ([fake_robot.py](fake_robot.py)) offline,
recording every command. ``build_robot`` selects one from the bridge config.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .config import AudioChannel, CameraResolution, NaoqiBridgeConfig

__all__ = [
    "AUDIO_CHANNEL_CODES",
    "AUDIO_SAMPLE_RATE",
    "CAMERAS",
    "CAMERA_COLORSPACE_BGR",
    "CAMERA_INDEXES",
    "CAMERA_NAMES",
    "CAMERA_RESOLUTION_CODES",
    "CAMERA_SUBSCRIBER_NAMES",
    "FRAME_ROBOT",
    "POSTURE_KEYS",
    "TOUCH_KEYS",
    "AudioCallback",
    "Camera",
    "CameraRead",
    "NaoqiRobot",
    "PostureCallback",
    "PostureKey",
    "RobotConnectionError",
    "TouchCallback",
    "TouchPart",
    "build_robot",
]

# The head's tactile sensors, by their ALMemory key.
type TouchPart = Literal[
    "FrontTactilTouched", "MiddleTactilTouched", "RearTactilTouched"
]
TOUCH_KEYS: tuple[TouchPart, ...] = (
    "FrontTactilTouched",
    "MiddleTactilTouched",
    "RearTactilTouched",
)

# Called on Naoqi's threads: (memory key, value 0/1).
type TouchCallback = Callable[[TouchPart, float], None]

# ALRobotPosture's events in ALMemory: the posture's name, and its family's.
type PostureKey = Literal["PostureChanged", "PostureFamilyChanged"]
POSTURE_KEYS: tuple[PostureKey, ...] = ("PostureChanged", "PostureFamilyChanged")
# Called on Naoqi's threads: (memory key, the new posture or family name).
type PostureCallback = Callable[[PostureKey, str], None]
# Called on Naoqi's threads: (channels, samples per channel, 16-bit LE PCM buffer).
type AudioCallback = Callable[[int, int, bytes], None]
AUDIO_SAMPLE_RATE = 16000
# ALAudioDevice.setClientPreferences channel configurations for one microphone at 16 kHz.
AUDIO_CHANNEL_CODES: dict[AudioChannel, int] = {
    "left": 1,
    "right": 2,
    "front": 3,
    "rear": 4,
}

# The robot's cameras (specs/camera.md "The cameras"): the bridge says "top" /
# "bottom", Naoqi has its own names and indexes.
type Camera = Literal["top", "bottom"]
CAMERAS: tuple[Camera, ...] = ("top", "bottom")
CAMERA_INDEXES: dict[Camera, int] = {"top": 0, "bottom": 1}
# ALMotion's names for the cameras' frames, for getTransform.
CAMERA_NAMES: dict[Camera, str] = {"top": "CameraTop", "bottom": "CameraBottom"}
# ALVideoDevice.subscribeCamera's resolution codes.
CAMERA_RESOLUTION_CODES: dict[CameraResolution, int] = {
    "qqvga": 0,
    "qvga": 1,
    "vga": 2,
    "4vga": 3,
}
# The subscriber name per camera; Naoqi allows seven handles per name (_0 … _6).
CAMERA_SUBSCRIBER_NAMES: dict[Camera, str] = {
    "top": "NaoqiBridgeCameraTop",
    "bottom": "NaoqiBridgeCameraBottom",
}
CAMERA_HANDLES_PER_NAME = 7
CAMERA_COLORSPACE_BGR = 13  # kBGRColorSpace
FRAME_ROBOT = 2  # ALMotion's frame on the ground between the feet


@dataclass(frozen=True)
class CameraRead:
    """What one camera pull returns, in Naoqi's terms (specs/camera.md "The seam")."""

    width: int
    height: int
    data: bytes  # BGR, 3 bytes per pixel, row-major
    naoqi_ts: float  # Naoqi's capture timestamp, seconds on the robot's clock
    fov: tuple[float, float]  # (left - right, top - bottom) angles, radians
    transform: tuple[float, ...]  # camera -> FRAME_ROBOT, a row-major 4x4


class RobotConnectionError(RuntimeError):
    """The robot could not be reached, or the real backend lacks the ``qi`` package."""


class NaoqiRobot(Protocol):
    """The Naoqi slice the bridge consumes. Every method blocks and raises on failure."""

    def connect(self, cancel: threading.Event | None = None) -> None: ...
    def close(self) -> None: ...
    def set_language(self, language: str) -> None: ...
    def say(self, text: str) -> None: ...
    def stop_speech(self) -> None: ...
    def wake_up(self) -> None: ...
    def rest(self) -> None: ...
    def is_awake(self) -> bool: ...
    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool: ...
    def stop_posture(self) -> None: ...
    def get_posture(self) -> tuple[str, str]: ...
    def subscribe_posture(self, callback: PostureCallback) -> None: ...
    def unsubscribe_posture(self) -> None: ...
    def set_breathing(self, chain_name: str, enabled: bool) -> None: ...
    def fade_eyes(self, color: str) -> None: ...
    def set_basic_awareness(
        self, enabled: bool, engagement_mode: str, tracking_mode: str
    ) -> None: ...
    def list_packages(self) -> list[dict[str, Any]]: ...
    def run_behavior(self, name: str) -> None: ...
    def stop_behavior(self, name: str) -> None: ...
    def get_joints(self) -> tuple[list[str], list[float]]: ...
    def subscribe_touch(self, callback: TouchCallback) -> None: ...
    def unsubscribe_touch(self) -> None: ...
    def subscribe_audio(
        self, callback: AudioCallback, channel: AudioChannel
    ) -> None: ...
    def unsubscribe_audio(self) -> None: ...
    def subscribe_camera(
        self, camera: Camera, resolution: CameraResolution, fps: int
    ) -> None: ...
    def read_camera(self, camera: Camera) -> CameraRead | None: ...
    def unsubscribe_camera(self, camera: Camera) -> None: ...


def build_robot(config: NaoqiBridgeConfig) -> NaoqiRobot:
    """Build (not connect) the robot for ``config.backend``: ``FakeNaoqiRobot``,
    ``RealNaoqiRobot`` at ``robot.ip``, or ``SimNaoqiRobot`` at naoqi-sim's fixed
    address."""
    # Imported here: both modules import this one for the shared types.
    from .fake_robot import FakeNaoqiRobot
    from .real_robot import RealNaoqiRobot

    if config.backend == "fake":
        return FakeNaoqiRobot()
    robot = config.robot
    if config.backend == "sim":
        from .sim import naoqi_sim_config
        from .sim_robot import SimNaoqiRobot

        return SimNaoqiRobot(
            connect_timeout_s=robot.connect_timeout_s,
            sit_through_crouch=naoqi_sim_config(config.sim).naoqi.version == "2.8",
        )
    return RealNaoqiRobot(
        robot.ip, robot.port, connect_timeout_s=robot.connect_timeout_s
    )
