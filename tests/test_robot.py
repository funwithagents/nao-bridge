"""The robot seam (specs/robot.md): backend selection, the real backend's connection
rules (with a stub ``qi`` module), and the fake's behavior-run and sensor simulation.

No robot, network or real ``qi`` needed. Async runs via ``asyncio.run``.
"""

import sys
import threading
import time
import types
from typing import Any, ClassVar

import pytest

from nao_bridge.config import NaoBridgeConfig, RobotSettings
from nao_bridge.robot import (
    FakeNaoRobot,
    QiNaoRobot,
    RobotConnectionError,
    build_robot,
)


def test_build_robot_follows_the_config():
    assert isinstance(build_robot(NaoBridgeConfig()), FakeNaoRobot)
    config = NaoBridgeConfig(
        backend="real",
        robot=RobotSettings(
            ip="10.0.0.5", port=9600, connect_tries=3, connect_timeout_s=2.5
        ),
    )
    real = build_robot(config)
    assert isinstance(real, QiNaoRobot)
    assert (real.ip, real.port, real.connect_tries, real.connect_timeout_s) == (
        "10.0.0.5",
        9600,
        3,
        2.5,
    )


def test_fake_ignores_the_robot_block():
    config = NaoBridgeConfig(backend="fake", robot=RobotSettings(ip="10.0.0.5"))
    assert isinstance(build_robot(config), FakeNaoRobot)


# --- QiNaoRobot ---------------------------------------------------------------


class _StubService:
    def __init__(
        self, calls: list[tuple[str, str, tuple[Any, ...]]], name: str
    ) -> None:
        self._calls = calls
        self._name = name

    def __getattr__(self, method: str) -> Any:
        def call(*args: Any) -> Any:
            self._calls.append((self._name, method, args))
            return True

        return call


class _StubFuture:
    """Stands in for the ``qi.Future`` of an async connect."""

    def __init__(self, finished: bool, error: str = "") -> None:
        self._finished = finished
        self._error = error
        self.waited_ms: int | None = None
        self.cancelled = False

    def wait(self, timeout_ms: int) -> None:
        self.waited_ms = timeout_ms

    def isFinished(self) -> bool:
        return self._finished

    def hasError(self) -> bool:
        return bool(self._error)

    def error(self) -> str:
        return self._error

    def cancel(self) -> None:
        self.cancelled = True


class _StubSession:
    """Stands in for ``qi.Session``: the first ``failures`` connects are refused and
    the next ``silent`` ones never answer; later ones connect."""

    failures: ClassVar[int] = 0
    silent: ClassVar[int] = 0
    connects: ClassVar[int] = 0
    closed: ClassVar[int] = 0
    futures: ClassVar[list[_StubFuture]] = []
    calls: ClassVar[list[tuple[str, str, tuple[Any, ...]]]] = []

    def connect(self, url: str, _async: bool = False) -> _StubFuture:
        assert _async, "connect must be asynchronous so a silent host can time out"
        cls = type(self)
        cls.connects += 1
        if cls.connects <= cls.failures:
            future = _StubFuture(finished=True, error=f"cannot reach {url}")
        elif cls.connects <= cls.failures + cls.silent:
            future = _StubFuture(finished=False)
        else:
            future = _StubFuture(finished=True)
        cls.futures.append(future)
        return future

    def service(self, name: str) -> _StubService:
        return _StubService(type(self).calls, name)

    def close(self) -> None:
        type(self).closed += 1

    def registerService(self, name: str, service: Any) -> int:
        type(self).calls.append(("session", "registerService", (name,)))
        return 7


@pytest.fixture
def stub_qi(monkeypatch: pytest.MonkeyPatch) -> type[_StubSession]:
    _StubSession.failures = 0
    _StubSession.silent = 0
    _StubSession.connects = 0
    _StubSession.closed = 0
    _StubSession.futures = []
    _StubSession.calls = []
    monkeypatch.setitem(sys.modules, "qi", types.SimpleNamespace(Session=_StubSession))
    return _StubSession


def test_real_backend_without_qi_fails_loudly_instead_of_faking(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "qi", None)  # makes `import qi` raise ImportError
    with pytest.raises(RobotConnectionError, match="qi"):
        QiNaoRobot("10.0.0.5").connect()


def test_real_backend_needs_an_address(stub_qi: type[_StubSession]):
    with pytest.raises(RobotConnectionError, match="IP"):
        QiNaoRobot("").connect()
    assert stub_qi.connects == 0


def test_real_backend_retries_then_connects(stub_qi: type[_StubSession]):
    stub_qi.failures = 3
    robot = QiNaoRobot("10.0.0.5")
    robot.connect()
    assert stub_qi.connects == 4
    assert stub_qi.closed == 3  # each failed attempt's session is released
    robot.say("hello")
    assert stub_qi.calls == [("ALAnimatedSpeech", "say", ("hello",))]


def test_real_backend_gives_up_after_its_tries(stub_qi: type[_StubSession]):
    stub_qi.failures = 3
    with pytest.raises(RobotConnectionError, match="after 3 tries") as caught:
        QiNaoRobot("10.0.0.5", connect_tries=3).connect()
    assert stub_qi.connects == 3
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("channel", "code"), [("front", 3), ("rear", 4), ("left", 1), ("right", 2)]
)
def test_real_backend_subscribes_to_the_configured_microphone(
    stub_qi: type[_StubSession], channel: Any, code: int
):
    robot = QiNaoRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_audio(lambda *_: None, channel)
    assert (
        "ALAudioDevice",
        "setClientPreferences",
        ("NaoBridgeAudio", 16000, code, 0),
    ) in (stub_qi.calls)


def test_real_backend_sets_posture_retries_before_moving(stub_qi: type[_StubSession]):
    robot = QiNaoRobot("10.0.0.5")
    robot.connect()
    assert robot.go_to_posture("Sit", 0.5, 2) is True
    assert stub_qi.calls == [
        ("ALRobotPosture", "setMaxTryNumber", (2,)),
        ("ALRobotPosture", "goToPosture", ("Sit", 0.5)),
    ]


# --- FakeNaoRobot -------------------------------------------------------------


def test_fake_behavior_runs_until_stopped():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("eagle-dance",))
    runner.start()
    while "eagle-dance" not in robot.running_behaviors:
        pass
    robot.stop_behavior("eagle-dance")
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert robot.running_behaviors == []


def test_fake_close_ends_running_behaviors():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("presentation",))
    runner.start()
    while not robot.running_behaviors:
        pass
    robot.close()
    runner.join(timeout=1.0)
    assert not runner.is_alive()


def test_fake_sensor_events_reach_only_a_subscribed_callback():
    robot = FakeNaoRobot()
    touches: list[tuple[str, float]] = []
    robot.touch("FrontTactilTouched", 1.0)  # nobody subscribed yet: dropped
    robot.subscribe_touch(lambda key, value: touches.append((key, value)))
    robot.touch("RearTactilTouched", 1.0)
    robot.unsubscribe_touch()
    robot.touch("MiddleTactilTouched", 0.0)
    assert touches == [("RearTactilTouched", 1.0)]


def test_fake_package_list_is_a_fresh_copy():
    robot = FakeNaoRobot()
    robot.list_packages()[0]["uuid"] = "tampered"
    assert robot.list_packages()[0]["uuid"] != "tampered"


def test_fake_pushes_paced_silence_while_audio_is_subscribed():
    robot = FakeNaoRobot()
    robot.audio_chunk_s = 0.01
    chunks: list[tuple[int, int, bytes]] = []
    robot.subscribe_audio(lambda *chunk: chunks.append(chunk), "front")
    time.sleep(0.2)
    robot.unsubscribe_audio()
    count = len(chunks)
    time.sleep(0.05)
    assert len(chunks) == count  # nothing pushed after unsubscribing
    assert 5 <= count <= 25  # about one per 10 ms
    assert chunks[0] == (1, 160, bytes(320))


def test_fake_audio_push_can_be_paused_for_injected_chunks():
    robot = FakeNaoRobot()
    robot.audio_chunk_s = None
    chunks: list[bytes] = []
    robot.subscribe_audio(lambda _c, _s, buffer: chunks.append(buffer), "front")
    robot.emit_audio(1, 1, b"\x01\x00")
    time.sleep(0.05)
    robot.close()
    assert chunks == [b"\x01\x00"]
