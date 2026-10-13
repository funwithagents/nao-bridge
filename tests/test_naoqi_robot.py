"""The real backend (specs/robot.md): its connection rules and Naoqi calls, against a
stub ``qi`` module. No robot, network or real ``qi`` needed.
"""

import sys
import threading
import time
import types
from typing import Any, ClassVar

import pytest

from naoqi_bridge.naoqi_robot import NaoqiRobot
from naoqi_bridge.robot import RobotConnectionError


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
        if not self._finished:  # a silent host: the wait runs out
            time.sleep(timeout_ms / 1000)

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
        NaoqiRobot("10.0.0.5").connect()


def test_real_backend_needs_an_address(stub_qi: type[_StubSession]):
    with pytest.raises(RobotConnectionError, match="IP"):
        NaoqiRobot("").connect()
    assert stub_qi.connects == 0


def test_real_backend_connects_and_reaches_naoqi(stub_qi: type[_StubSession]):
    robot = NaoqiRobot("10.0.0.5")
    robot.connect()
    robot.say("hello")
    assert stub_qi.calls == [("ALAnimatedSpeech", "say", ("hello",))]


def test_real_backend_does_not_retry_a_failed_connect(stub_qi: type[_StubSession]):
    stub_qi.failures = 1  # a second attempt would succeed
    with pytest.raises(RobotConnectionError, match="cannot reach") as caught:
        NaoqiRobot("10.0.0.5").connect()
    assert stub_qi.connects == 1
    assert stub_qi.closed == 1  # the failed attempt's session is released
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_real_backend_gives_up_on_a_silent_host_at_its_timeout(
    stub_qi: type[_StubSession],
):
    stub_qi.silent = 1
    started = time.monotonic()
    with pytest.raises(RobotConnectionError, match="no answer within 0.2 s"):
        NaoqiRobot("10.0.0.5", connect_timeout_s=0.2).connect()
    assert 0.2 <= time.monotonic() - started < 1.0
    assert stub_qi.connects == 1
    assert stub_qi.futures[0].cancelled
    assert stub_qi.closed == 1


def test_real_backend_gives_up_a_connect_in_flight_when_cancelled(
    stub_qi: type[_StubSession],
):
    stub_qi.silent = 1
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(RobotConnectionError, match="cancelled"):
        NaoqiRobot("10.0.0.5", connect_timeout_s=10.0).connect(cancel)
    assert time.monotonic() - started < 1.0  # not the 10 s timeout
    assert stub_qi.futures[0].cancelled
    assert stub_qi.closed == 1


def test_real_backend_already_cancelled_makes_no_attempt(
    stub_qi: type[_StubSession],
):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RobotConnectionError, match="cancelled"):
        NaoqiRobot("10.0.0.5").connect(cancel)
    assert stub_qi.connects == 0


@pytest.mark.parametrize(
    ("channel", "code"), [("front", 3), ("rear", 4), ("left", 1), ("right", 2)]
)
def test_real_backend_subscribes_to_the_configured_microphone(
    stub_qi: type[_StubSession], channel: Any, code: int
):
    robot = NaoqiRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_audio(lambda *_: None, channel)
    assert (
        "ALAudioDevice",
        "setClientPreferences",
        ("NaoqiBridgeAudio", 16000, code, 0),
    ) in (stub_qi.calls)


def test_real_backend_refuses_robot_calls_while_disconnected(
    stub_qi: type[_StubSession],
):
    robot = NaoqiRobot("10.0.0.5")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.say("hello")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.subscribe_audio(lambda *_: None, "front")
    assert stub_qi.calls == []


def test_real_backend_close_forgets_its_subscriptions(stub_qi: type[_StubSession]):
    robot = NaoqiRobot("10.0.0.5")
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
    robot = NaoqiRobot("10.0.0.5")
    robot.connect()
    assert robot.is_awake() is True
    assert stub_qi.calls == [("ALMotion", "robotIsWakeUp", ())]


def test_real_backend_sets_posture_retries_before_moving(stub_qi: type[_StubSession]):
    robot = NaoqiRobot("10.0.0.5")
    robot.connect()
    assert robot.go_to_posture("Sit", 0.5, 2) is True
    assert stub_qi.calls == [
        ("ALRobotPosture", "setMaxTryNumber", (2,)),
        ("ALRobotPosture", "goToPosture", ("Sit", 0.5)),
    ]


def test_real_backend_stops_a_posture_move(stub_qi: type[_StubSession]):
    robot = NaoqiRobot("10.0.0.5")
    robot.connect()
    robot.stop_posture()
    assert stub_qi.calls == [("ALRobotPosture", "stopMove", ())]


class _Posture28:
    """ALRobotPosture as on NAOqi 2.8's desktop robot (naoqi-sim): Stand -> Sit
    leaves it standing, and from Crouch it reaches Sit yet reports False. Other
    moves work. ``hold`` keeps a move in flight until ``stopMove``."""

    def __init__(self, posture: str) -> None:
        self.posture = posture
        self.moves: list[str] = []
        self.hold: str | None = None
        self.stopped = threading.Event()

    def setMaxTryNumber(self, tries: int) -> None:
        pass

    def getPosture(self) -> str:
        return self.posture

    def goToPosture(self, posture: str, speed: float) -> bool:
        self.moves.append(posture)
        if posture == self.hold:
            self.stopped.wait(5.0)
            return False
        if posture == "Sit":
            if self.posture == "Crouch":
                self.posture = "Sit"
            return False
        self.posture = posture
        return True

    def stopMove(self) -> None:
        self.stopped.set()


def _robot_on(posture: _Posture28, *, sit_through_crouch: bool) -> NaoqiRobot:
    robot = NaoqiRobot("127.0.0.1", sit_through_crouch=sit_through_crouch)
    robot.connect()
    robot._services["ALRobotPosture"] = posture  # pyright: ignore[reportPrivateUsage]
    return robot


def test_sit_is_asked_directly_and_its_result_trusted_by_default(
    stub_qi: type[_StubSession],
):
    posture = _Posture28("Stand")
    assert (
        _robot_on(posture, sit_through_crouch=False).go_to_posture("Sit", 0.8, 3)
        is False
    )
    assert posture.moves == ["Sit"]


@pytest.mark.parametrize(
    ("start", "moves"), [("Stand", ["Crouch", "Sit"]), ("Crouch", ["Sit"])]
)
def test_the_2_8_sim_sits_through_crouch_and_judges_by_the_posture_reached(
    stub_qi: type[_StubSession], start: str, moves: list[str]
):
    posture = _Posture28(start)
    robot = _robot_on(posture, sit_through_crouch=True)
    # goToPosture("Sit") reports False, yet the robot sits: success.
    assert robot.go_to_posture("Sit", 0.8, 3) is True
    assert (posture.moves, posture.posture) == (moves, "Sit")
    # Other postures are asked for directly, as on any Naoqi.
    assert robot.go_to_posture("Stand", 0.8, 3) is True
    assert posture.moves[-1:] == ["Stand"] and len(posture.moves) == len(moves) + 1


def test_a_stop_during_the_crouch_leg_ends_the_sit(stub_qi: type[_StubSession]):
    posture = _Posture28("Stand")
    posture.hold = "Crouch"
    robot = _robot_on(posture, sit_through_crouch=True)
    result: list[bool] = []
    sitting = threading.Thread(
        target=lambda: result.append(robot.go_to_posture("Sit", 0.8, 3))
    )
    sitting.start()
    time.sleep(0.05)
    robot.stop_posture()
    sitting.join(2.0)
    assert result == [False]
    assert posture.moves == ["Crouch"]  # never went on to Sit


class _AnimatedSpeech:
    """ALAnimatedSpeech: ``say`` runs until ``_stopAll`` ends it with Naoqi's
    "Future canceled" error, or raises ``fails_with``."""

    def __init__(self, fails_with: str = "") -> None:
        self.fails_with = fails_with
        self.stopped = threading.Event()
        self.calls: list[str] = []

    def say(self, text: str) -> None:
        if self.fails_with:
            raise RuntimeError(self.fails_with)
        if self.stopped.wait(5.0):
            raise RuntimeError("Future canceled.")

    def _stopAll(self, blocking: bool) -> None:
        self.calls.append(f"_stopAll({blocking})")
        self.stopped.set()


def _speaking_robot(stub_qi: type[_StubSession], speech: _AnimatedSpeech) -> NaoqiRobot:
    robot = NaoqiRobot("127.0.0.1")
    robot.connect()
    robot._services["ALAnimatedSpeech"] = speech  # pyright: ignore[reportPrivateUsage]
    return robot


def test_stop_speech_ends_a_say_at_once_and_the_say_returns(
    stub_qi: type[_StubSession],
):
    speech = _AnimatedSpeech()
    robot = _speaking_robot(stub_qi, speech)
    outcome: list[object] = []

    def say() -> None:
        try:
            robot.say("a long sentence")
            outcome.append("returned")
        except RuntimeError as e:
            outcome.append(e)

    saying = threading.Thread(target=say)
    saying.start()
    time.sleep(0.05)
    robot.stop_speech()
    saying.join(1.0)
    # Stopped is how a say ends, though Naoqi's call raised "Future canceled".
    assert outcome == ["returned"]
    # ALAnimatedSpeech's own stop (at once), then the TTS's.
    assert speech.calls == ["_stopAll(False)"]
    assert ("ALTextToSpeech", "stopAll", ()) in stub_qi.calls


def test_a_say_naoqi_fails_without_a_stop_still_raises(stub_qi: type[_StubSession]):
    robot = _speaking_robot(stub_qi, _AnimatedSpeech(fails_with="no voice"))
    robot.stop_speech()  # a stop before this say does not excuse its failure
    with pytest.raises(RuntimeError, match="no voice"):
        robot.say("hello")
