"""The ``fake`` backend: an offline ``NaoRobot`` that records every command.

Specified by [specs/robot.md](../../specs/robot.md). It serves a fixed ``packages2``-shaped
package list, simulates behavior runs and sensor events, and pushes silent audio.
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from .config import AudioChannel
from .robot import AUDIO_SAMPLE_RATE, AudioCallback, TouchCallback

__all__ = ["FakeNaoRobot"]


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


class FakeNaoRobot:
    """Offline ``NaoRobot``: records commands, serves a fixed package list.

    Tests reach it through ``bridge.robot`` to assert on ``commands``, tune
    ``behavior_duration_s`` / ``posture_succeeds``, and fire sensor events with
    ``touch`` / ``emit_audio``. While audio is subscribed, a thread pushes a silent
    mono chunk every ``audio_chunk_s`` seconds, as Naoqi pushes its buffers; setting
    ``audio_chunk_s`` to ``None`` pauses it, so a test pushes only what it emits.
    """

    # How long a behavior runs unless stopped: long enough to be seen running and
    # stopped, as on a robot. The fast tier sets it to 0 (tests/conftest.py).
    DEFAULT_BEHAVIOR_DURATION_S = 5.0

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.connected = False
        self.behavior_duration_s = self.DEFAULT_BEHAVIOR_DURATION_S
        self.posture_succeeds = True
        self.joint_names = ["HeadYaw", "HeadPitch"]
        self.joint_angles = [0.0, 0.1]
        self._running: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._touch_callback: TouchCallback | None = None
        self._audio_callback: AudioCallback | None = None
        self.audio_chunk_s: float | None = 0.085
        self._audio_stop = threading.Event()
        self._audio_thread: threading.Thread | None = None

    def _record(self, method: str, **args: Any) -> None:
        self.commands.append((method, args))

    @property
    def running_behaviors(self) -> list[str]:
        with self._lock:
            return list(self._running)

    def connect(self) -> None:
        self._record("connect")
        self.connected = True

    def close(self) -> None:
        self._record("close")
        self.connected = False
        self._stop_audio_push()
        with self._lock:
            for stop in self._running.values():
                stop.set()

    def set_language(self, language: str) -> None:
        self._record("set_language", language=language)

    def say(self, text: str) -> None:
        self._record("say", text=text)

    def stop_speech(self) -> None:
        self._record("stop_speech")

    def wake_up(self) -> None:
        self._record("wake_up")

    def rest(self) -> None:
        self._record("rest")

    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool:
        self._record("go_to_posture", posture=posture, speed=speed, max_tries=max_tries)
        return self.posture_succeeds

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
        with self._lock:
            stop = self._running.get(name)
        if stop is not None:
            stop.set()

    def get_joints(self) -> tuple[list[str], list[float]]:
        return list(self.joint_names), list(self.joint_angles)

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
            target=self._push_audio, name="fake-nao-audio", daemon=True
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

    def touch(self, key: str, value: float) -> None:
        """Simulate a tactile sensor event, as Naoqi would fire it."""
        if self._touch_callback is not None:
            self._touch_callback(key, value)

    def emit_audio(
        self, channels: int, samples_per_channel: int, buffer: bytes
    ) -> None:
        """Simulate a microphone buffer, as Naoqi would push it."""
        if self._audio_callback is not None:
            self._audio_callback(channels, samples_per_channel, buffer)
