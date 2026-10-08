"""Connection seam between Nao Bridge and a Naoqi robot.

Specified by [specs/robot.md](../../specs/robot.md). ``NaoRobot`` is the Protocol listing
the Naoqi capabilities the bridge consumes, with the types and constants both
implementations share. ``RealNaoRobot`` ([real_robot.py](real_robot.py)) implements it
over a ``qi`` session and ``FakeNaoRobot`` ([fake_robot.py](fake_robot.py)) offline,
recording every command. ``build_robot`` selects one from the bridge config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .config import AudioChannel, Backend, NaoBridgeConfig

__all__ = [
    "AUDIO_CHANNEL_CODES",
    "AUDIO_SAMPLE_RATE",
    "TOUCH_KEYS",
    "AudioCallback",
    "Backend",
    "NaoRobot",
    "RobotConnectionError",
    "TouchCallback",
    "build_robot",
]

# Called on Naoqi's threads: (memory key, value 0/1).
type TouchCallback = Callable[[str, float], None]
# Called on Naoqi's threads: (channels, samples per channel, 16-bit LE PCM buffer).
type AudioCallback = Callable[[int, int, bytes], None]

TOUCH_KEYS = ("FrontTactilTouched", "MiddleTactilTouched", "RearTactilTouched")
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


class NaoRobot(Protocol):
    """The Naoqi slice the bridge consumes. Every method blocks and raises on failure."""

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def set_language(self, language: str) -> None: ...
    def say(self, text: str) -> None: ...
    def stop_speech(self) -> None: ...
    def wake_up(self) -> None: ...
    def rest(self) -> None: ...
    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool: ...
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


def build_robot(config: NaoBridgeConfig) -> NaoRobot:
    """Build (not connect) the robot for ``config.backend``: ``fake`` or ``real``."""
    # Imported here: both modules import this one for the shared types.
    from .fake_robot import FakeNaoRobot
    from .real_robot import RealNaoRobot

    if config.backend == "fake":
        return FakeNaoRobot()
    robot = config.robot
    return RealNaoRobot(
        robot.ip,
        robot.port,
        connect_tries=robot.connect_tries,
        connect_timeout_s=robot.connect_timeout_s,
    )
