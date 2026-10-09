"""The real backend (specs/robot.md): its connection rules and Naoqi calls, against a
stub ``qi`` module. No robot, network or real ``qi`` needed.
"""

import sys
import types
from typing import Any, ClassVar

import pytest

from nao_bridge.real_robot import RealNaoRobot
from nao_bridge.robot import RobotConnectionError


class _StubSignal:
    """An ALMemory subscriber's ``signal``: records connects and disconnects."""

    def __init__(self, calls: list[tuple[str, str, tuple[Any, ...]]], key: str) -> None:
        self._calls = calls
        self._key = key

    def connect(self, handler: Any) -> int:
        self._calls.append(("ALMemory", "connect", (self._key,)))
        return 1

    def disconnect(self, link: int) -> None:
        self._calls.append(("ALMemory", "disconnect", (self._key,)))


class _StubSubscriber:
    def __init__(self, calls: list[tuple[str, str, tuple[Any, ...]]], key: str) -> None:
        self.signal = _StubSignal(calls, key)


class _StubService:
    def __init__(
        self, calls: list[tuple[str, str, tuple[Any, ...]]], name: str
    ) -> None:
        self._calls = calls
        self._name = name

    def __getattr__(self, method: str) -> Any:
        if method == "subscriber":
            return lambda key: _StubSubscriber(self._calls, key)

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

    def unregisterService(self, service_id: int) -> None:
        type(self).calls.append(("session", "unregisterService", (service_id,)))


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
        RealNaoRobot("10.0.0.5").connect()


def test_real_backend_needs_an_address(stub_qi: type[_StubSession]):
    with pytest.raises(RobotConnectionError, match="IP"):
        RealNaoRobot("").connect()
    assert stub_qi.connects == 0


def test_real_backend_retries_then_connects(stub_qi: type[_StubSession]):
    stub_qi.failures = 3
    robot = RealNaoRobot("10.0.0.5")
    robot.connect()
    assert stub_qi.connects == 4
    assert stub_qi.closed == 3  # each failed attempt's session is released
    robot.say("hello")
    assert stub_qi.calls == [("ALAnimatedSpeech", "say", ("hello",))]


def test_real_backend_gives_up_after_its_tries(stub_qi: type[_StubSession]):
    stub_qi.failures = 3
    with pytest.raises(RobotConnectionError, match="after 3 tries") as caught:
        RealNaoRobot("10.0.0.5", connect_tries=3).connect()
    assert stub_qi.connects == 3
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("channel", "code"), [("front", 3), ("rear", 4), ("left", 1), ("right", 2)]
)
def test_real_backend_subscribes_to_the_configured_microphone(
    stub_qi: type[_StubSession], channel: Any, code: int
):
    robot = RealNaoRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_audio(lambda *_: None, channel)
    assert (
        "ALAudioDevice",
        "setClientPreferences",
        ("NaoBridgeAudio", 16000, code, 0),
    ) in (stub_qi.calls)


def test_real_backend_refuses_robot_calls_while_disconnected(
    stub_qi: type[_StubSession],
):
    robot = RealNaoRobot("10.0.0.5")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.say("hello")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.subscribe_audio(lambda *_: None, "front")
    assert stub_qi.calls == []


def test_real_backend_close_forgets_its_subscriptions(stub_qi: type[_StubSession]):
    robot = RealNaoRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_touch(lambda key, value: None)
    robot.subscribe_audio(lambda *_: None, "front")
    robot.close()
    stub_qi.calls.clear()
    # Nothing left to release: no disconnect, no unregister, and no error either.
    robot.unsubscribe_touch()
    robot.unsubscribe_audio()
    assert stub_qi.calls == []


def test_real_backend_asks_motion_whether_the_robot_is_awake(
    stub_qi: type[_StubSession],
):
    robot = RealNaoRobot("10.0.0.5")
    robot.connect()
    assert robot.is_awake() is True
    assert stub_qi.calls == [("ALMotion", "robotIsWakeUp", ())]


def test_real_backend_sets_posture_retries_before_moving(stub_qi: type[_StubSession]):
    robot = RealNaoRobot("10.0.0.5")
    robot.connect()
    assert robot.go_to_posture("Sit", 0.5, 2) is True
    assert stub_qi.calls == [
        ("ALRobotPosture", "setMaxTryNumber", (2,)),
        ("ALRobotPosture", "goToPosture", ("Sit", 0.5)),
    ]
