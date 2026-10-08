"""The ``real`` backend: ``NaoRobot`` over a ``qi`` session to a Nao.

Specified by [specs/robot.md](../../specs/robot.md). ``qi`` is imported lazily on
``connect()``, so this module (and ``nao_bridge``) imports where ``qi`` isn't installed.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from .config import AudioChannel
from .robot import (
    AUDIO_CHANNEL_CODES,
    AUDIO_SAMPLE_RATE,
    TOUCH_KEYS,
    AudioCallback,
    RobotConnectionError,
    TouchCallback,
)

__all__ = ["RealNaoRobot"]

logger = logging.getLogger(__name__)


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


class RealNaoRobot:
    """``NaoRobot`` over a ``qi`` session to a real (or Choregraphe-simulated) robot."""

    AUDIO_SERVICE_NAME = "NaoBridgeAudio"

    def __init__(
        self,
        ip: str,
        port: int = 9559,
        *,
        connect_tries: int = 10,
        connect_timeout_s: float = 5.0,
    ) -> None:
        self.ip = ip
        self.port = port
        self.connect_tries = connect_tries
        self.connect_timeout_s = connect_timeout_s
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
                "the real backend needs the `qi` package, which nao-bridge installs on "
                "macOS arm64 and Linux x86_64 with CPython 3.12 / 3.13 (run `uv sync`); "
                "there is no qi wheel for other platforms, which run the fake backend only"
            ) from e

        url = f"tcp://{self.ip}:{self.port}"
        timeout_ms = max(1, round(self.connect_timeout_s * 1000))
        last_error: Exception | None = None
        timed_out = 0
        for attempt in range(1, self.connect_tries + 1):
            session = qi.Session()
            # Asynchronous, so a silent host costs connect_timeout_s, not the OS TCP
            # timeout: the future is still running at the deadline.
            future = session.connect(url, _async=True)
            future.wait(timeout_ms)
            if not future.isFinished():
                future.cancel()
                session.close()
                timed_out += 1
                last_error = TimeoutError(
                    f"no answer within {self.connect_timeout_s:g} s"
                )
                logger.warning(
                    "Connection attempt %d to %s timed out after %g s",
                    attempt,
                    url,
                    self.connect_timeout_s,
                )
                continue
            if future.hasError():
                session.close()
                last_error = RuntimeError(future.error())
                logger.warning(
                    "Connection attempt %d to %s failed: %s", attempt, url, last_error
                )
                continue
            self._session = session
            logger.debug("Connected to %s", url)
            return
        detail = (
            f" ({timed_out} timed out after {self.connect_timeout_s:g} s)"
            if timed_out
            else ""
        )
        raise RobotConnectionError(
            f"could not connect to {url} after {self.connect_tries} tries{detail}"
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

    def subscribe_audio(self, callback: AudioCallback, channel: AudioChannel) -> None:
        self._audio_service_id = self._session.registerService(
            self.AUDIO_SERVICE_NAME, _AudioSink(callback)
        )
        audio_device = self._service("ALAudioDevice")
        audio_device.setClientPreferences(
            self.AUDIO_SERVICE_NAME, AUDIO_SAMPLE_RATE, AUDIO_CHANNEL_CODES[channel], 0
        )
        audio_device.subscribe(self.AUDIO_SERVICE_NAME)

    def unsubscribe_audio(self) -> None:
        if self._audio_service_id is None:
            return
        self._service("ALAudioDevice").unsubscribe(self.AUDIO_SERVICE_NAME)
        self._session.unregisterService(self._audio_service_id)
        self._audio_service_id = None
