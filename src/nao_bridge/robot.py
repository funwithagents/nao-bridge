"""Connection seam between Nao Bridge and a Naoqi robot.

Specified by [specs/robot.md](../../specs/robot.md). ``NaoRobot`` is the Protocol listing
the Naoqi capabilities the bridge consumes; ``QiNaoRobot`` implements it over a ``qi``
session (imported lazily, so ``qi`` is only needed for the real backend) and
``FakeNaoRobot`` implements it offline, recording every command. ``build_robot``
selects one from a backend string.
"""

from __future__ import annotations

import copy
import importlib
import logging
import threading
from collections.abc import Callable
from typing import Any, Literal, Protocol

__all__ = [
    "AUDIO_SAMPLE_RATE",
    "TOUCH_KEYS",
    "AudioCallback",
    "Backend",
    "FakeNaoRobot",
    "NaoRobot",
    "QiNaoRobot",
    "RobotConnectionError",
    "TouchCallback",
    "build_robot",
]

logger = logging.getLogger(__name__)

type Backend = Literal["real", "fake"]
# Called on Naoqi's threads: (memory key, value 0/1).
type TouchCallback = Callable[[str, float], None]
# Called on Naoqi's threads: (channels, samples per channel, 16-bit LE PCM buffer).
type AudioCallback = Callable[[int, int, bytes], None]

TOUCH_KEYS = ("FrontTactilTouched", "MiddleTactilTouched", "RearTactilTouched")
AUDIO_SAMPLE_RATE = 16000


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
    def subscribe_audio(self, callback: AudioCallback) -> None: ...
    def unsubscribe_audio(self) -> None: ...


def build_robot(
    backend: Backend = "real", *, ip: str = "", port: int = 9559
) -> NaoRobot:
    """Build (not connect) the robot for ``backend``: ``fake`` or ``real``."""
    if backend == "fake":
        return FakeNaoRobot()
    if backend == "real":
        return QiNaoRobot(ip, port)
    raise ValueError(f"unknown backend {backend!r}; expected 'real' or 'fake'")


# region Real robot


class _AudioSink:
    """The service object Naoqi pushes microphone buffers to.

    Naoqi calls a method named exactly ``processRemote`` on the registered service.
    """

    def __init__(self, callback: AudioCallback) -> None:
        self._callback = callback

    def processRemote(
        self,
        nbOfChannels: int,
        nbOfSamplesByChannel: int,
        timeStamp: Any,
        inputBuffer: Any,
    ) -> None:
        self._callback(nbOfChannels, nbOfSamplesByChannel, bytes(inputBuffer))


class QiNaoRobot:
    """``NaoRobot`` over a ``qi`` session to a real (or Choregraphe-simulated) robot."""

    CONNECT_TRIES = 10
    AUDIO_SERVICE_NAME = "NaoBridgeAudio"

    def __init__(self, ip: str, port: int = 9559) -> None:
        self.ip = ip
        self.port = port
        self._session: Any = None
        self._services: dict[str, Any] = {}
        self._touch_links: list[tuple[Any, Any]] = []
        self._audio_service_id: Any = None

    def connect(self) -> None:
        if not self.ip or self.port <= 0:
            raise RobotConnectionError(
                "the real backend needs a robot IP address and port"
            )
        try:
            qi = importlib.import_module("qi")
        except ImportError as e:
            raise RobotConnectionError(
                "the real backend needs the `qi` package: install the wheel for your "
                "platform from https://github.com/funwithagents/libqi-python/releases "
                "(or use the fake backend)"
            ) from e

        url = f"tcp://{self.ip}:{self.port}"
        last_error: Exception | None = None
        for attempt in range(1, self.CONNECT_TRIES + 1):
            session = qi.Session()
            try:
                session.connect(url)
            except RuntimeError as e:
                last_error = e
                logger.warning(
                    "Connection attempt %d to %s failed: %s", attempt, url, e
                )
                continue
            self._session = session
            logger.debug("Connected to %s", url)
            return
        raise RobotConnectionError(
            f"could not connect to {url} after {self.CONNECT_TRIES} tries"
        ) from last_error

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
        self._session = None
        self._services.clear()

    def _service(self, name: str) -> Any:
        if self._session is None:
            raise RobotConnectionError("not connected")
        service = self._services.get(name)
        if service is None:
            service = self._services[name] = self._session.service(name)
        return service

    def set_language(self, language: str) -> None:
        self._service("ALTextToSpeech").setLanguage(language)

    def say(self, text: str) -> None:
        self._service("ALAnimatedSpeech").say(text)

    def stop_speech(self) -> None:
        self._service("ALTextToSpeech").stopAll()

    def wake_up(self) -> None:
        self._service("ALMotion").wakeUp()

    def rest(self) -> None:
        self._service("ALMotion").rest()

    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool:
        robot_posture = self._service("ALRobotPosture")
        robot_posture.setMaxTryNumber(max_tries)
        return bool(robot_posture.goToPosture(posture, speed))

    def set_breathing(self, chain_name: str, enabled: bool) -> None:
        self._service("ALMotion").setBreathEnabled(chain_name, enabled)

    def fade_eyes(self, color: str) -> None:
        self._service("ALLeds").fadeRGB("FaceLeds", color, 0)

    def set_basic_awareness(
        self, enabled: bool, engagement_mode: str, tracking_mode: str
    ) -> None:
        awareness = self._service("ALBasicAwareness")
        awareness.setEngagementMode(engagement_mode)
        awareness.setTrackingMode(tracking_mode)
        if enabled:
            awareness.startAwareness()
        else:
            awareness.stopAwareness()

    def list_packages(self) -> list[dict[str, Any]]:
        return list(self._service("PackageManager").packages2())

    def run_behavior(self, name: str) -> None:
        self._service("ALBehaviorManager").runBehavior(name)

    def stop_behavior(self, name: str) -> None:
        self._service("ALBehaviorManager").stopBehavior(name)

    def get_joints(self) -> tuple[list[str], list[float]]:
        motion = self._service("ALMotion")
        return list(motion.getBodyNames("Body")), list(motion.getAngles("Body", False))

    def subscribe_touch(self, callback: TouchCallback) -> None:
        memory = self._service("ALMemory")
        for key in TOUCH_KEYS:
            subscriber = memory.subscriber(key)
            link = subscriber.signal.connect(
                lambda value, key=key: callback(key, value)
            )
            self._touch_links.append((subscriber, link))

    def unsubscribe_touch(self) -> None:
        for subscriber, link in self._touch_links:
            subscriber.signal.disconnect(link)
        self._touch_links.clear()

    def subscribe_audio(self, callback: AudioCallback) -> None:
        self._audio_service_id = self._session.registerService(
            self.AUDIO_SERVICE_NAME, _AudioSink(callback)
        )
        audio_device = self._service("ALAudioDevice")
        audio_device.setClientPreferences(
            self.AUDIO_SERVICE_NAME, AUDIO_SAMPLE_RATE, 3, 0
        )
        audio_device.subscribe(self.AUDIO_SERVICE_NAME)

    def unsubscribe_audio(self) -> None:
        if self._audio_service_id is None:
            return
        self._service("ALAudioDevice").unsubscribe(self.AUDIO_SERVICE_NAME)
        self._session.unregisterService(self._audio_service_id)
        self._audio_service_id = None


# endregion

# region Fake robot


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


def _animation_package(
    uuid: str, behaviors: list[tuple[str, list[str]]]
) -> dict[str, Any]:
    """A package of sub-behaviors, each a ``(path, en_US tags)`` pair, in packages2 shape."""
    return {
        "uuid": uuid,
        "elems": {
            "names": {},
            "descriptions": {},
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
    _animation_package(
        "animations",
        [
            ("Stand/Emotions/Positive/Happy_1", ["happy"]),
            ("Stand/Emotions/Positive/Happy_2", ["happy"]),
            ("Stand/Emotions/Positive/Proud_1", ["proud"]),
            ("Stand/Emotions/Positive/Laugh_1", ["laugh"]),
            ("Stand/Emotions/Negative/Sad_1", ["sad"]),
            ("Sit/Emotions/Positive/Happy_1", ["happy"]),
        ],
    ),
    _animation_package("dialog_touch", [("animations/head_touched", [])]),
    _animation_package(
        "dialog_move_arms",
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
    ``touch`` / ``emit_audio``.
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.connected = False
        self.behavior_duration_s = 0.0
        self.posture_succeeds = True
        self.joint_names = ["HeadYaw", "HeadPitch"]
        self.joint_angles = [0.0, 0.1]
        self._running: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._touch_callback: TouchCallback | None = None
        self._audio_callback: AudioCallback | None = None

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

    def subscribe_audio(self, callback: AudioCallback) -> None:
        self._record("subscribe_audio")
        self._audio_callback = callback

    def unsubscribe_audio(self) -> None:
        self._record("unsubscribe_audio")
        self._audio_callback = None

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


# endregion
