"""Connection seam between naoqi-bridge and a Naoqi robot.

Specified by [specs/robot.md](../../specs/robot.md). ``AnyNaoqiRobot`` is the Protocol listing
the Naoqi capabilities the bridge consumes, with the types and constants both
implementations share. ``NaoqiRobot`` ([naoqi_robot.py](naoqi_robot.py)) implements it
over a ``qi`` session and ``FakeNaoqiRobot`` ([fake_robot.py](fake_robot.py)) offline,
recording every command. ``build_robot`` selects one from the bridge config.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Literal, Protocol

from .config import AudioChannel, NaoqiBridgeConfig

__all__ = [
    "AUDIO_CHANNEL_CODES",
    "AUDIO_SAMPLE_RATE",
    "TOUCH_KEYS",
    "AnyNaoqiRobot",
    "AudioCallback",
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


class RobotConnectionError(RuntimeError):
    """The robot could not be reached, or the real backend lacks the ``qi`` package."""


class AnyNaoqiRobot(Protocol):
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


def build_robot(config: NaoqiBridgeConfig) -> AnyNaoqiRobot:
    """Build (not connect) the robot for ``config.backend``: ``fake`` or ``real``."""
    # Imported here: both modules import this one for the shared types.
    from .fake_robot import FakeNaoqiRobot
    from .naoqi_robot import NaoqiRobot

    if config.backend == "fake":
        return FakeNaoqiRobot()
    robot = config.robot
    return NaoqiRobot(robot.ip, robot.port, connect_timeout_s=robot.connect_timeout_s)
