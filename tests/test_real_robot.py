"""The real backend (specs/robot.md): its connection rules and Naoqi calls, against a
stub ``qi`` module. No robot, network or real ``qi`` needed.
"""

import sys
import threading
import time
from typing import Any

import pytest
from qi_stub import StubSession

from naoqi_bridge.real_robot import RealNaoqiRobot
from naoqi_bridge.robot import RobotConnectionError


def test_real_backend_without_qi_fails_loudly_instead_of_faking(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "qi", None)  # makes `import qi` raise ImportError
    with pytest.raises(RobotConnectionError, match="qi"):
        RealNaoqiRobot("10.0.0.5").connect()


def test_real_backend_needs_an_address(stub_qi: type[StubSession]):
    with pytest.raises(RobotConnectionError, match="IP"):
        RealNaoqiRobot("").connect()
    assert stub_qi.connects == 0


def test_real_backend_connects_and_reaches_naoqi(stub_qi: type[StubSession]):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    robot.say("hello")
    assert stub_qi.calls == [("ALAnimatedSpeech", "say", ("hello",))]


def test_real_backend_does_not_retry_a_failed_connect(stub_qi: type[StubSession]):
    stub_qi.failures = 1  # a second attempt would succeed
    with pytest.raises(RobotConnectionError, match="cannot reach") as caught:
        RealNaoqiRobot("10.0.0.5").connect()
    assert stub_qi.connects == 1
    assert stub_qi.closed == 1  # the failed attempt's session is released
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_real_backend_gives_up_on_a_silent_host_at_its_timeout(
    stub_qi: type[StubSession],
):
    stub_qi.silent = 1
    started = time.monotonic()
    with pytest.raises(RobotConnectionError, match="no answer within 0.2 s"):
        RealNaoqiRobot("10.0.0.5", connect_timeout_s=0.2).connect()
    assert 0.2 <= time.monotonic() - started < 1.0
    assert stub_qi.connects == 1
    assert stub_qi.futures[0].cancelled
    assert stub_qi.closed == 1


def test_real_backend_gives_up_a_connect_in_flight_when_cancelled(
    stub_qi: type[StubSession],
):
    stub_qi.silent = 1
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(RobotConnectionError, match="cancelled"):
        RealNaoqiRobot("10.0.0.5", connect_timeout_s=10.0).connect(cancel)
    assert time.monotonic() - started < 1.0  # not the 10 s timeout
    assert stub_qi.futures[0].cancelled
    assert stub_qi.closed == 1


def test_real_backend_already_cancelled_makes_no_attempt(
    stub_qi: type[StubSession],
):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RobotConnectionError, match="cancelled"):
        RealNaoqiRobot("10.0.0.5").connect(cancel)
    assert stub_qi.connects == 0


@pytest.mark.parametrize(
    ("channel", "code"), [("front", 3), ("rear", 4), ("left", 1), ("right", 2)]
)
def test_real_backend_subscribes_to_the_configured_microphone(
    stub_qi: type[StubSession], channel: Any, code: int
):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_audio(lambda *_: None, channel)
    assert (
        "ALAudioDevice",
        "setClientPreferences",
        ("NaoqiBridgeAudio", 16000, code, 0),
    ) in (stub_qi.calls)


def test_real_backend_refuses_robot_calls_while_disconnected(
    stub_qi: type[StubSession],
):
    robot = RealNaoqiRobot("10.0.0.5")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.say("hello")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.subscribe_audio(lambda *_: None, "front")
    assert stub_qi.calls == []


def test_real_backend_close_forgets_its_subscriptions(stub_qi: type[StubSession]):
    robot = RealNaoqiRobot("10.0.0.5")
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
    stub_qi: type[StubSession],
):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    assert robot.is_awake() is True
    assert stub_qi.calls == [("ALMotion", "robotIsWakeUp", ())]


def test_real_backend_sets_posture_retries_before_moving(stub_qi: type[StubSession]):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    assert robot.go_to_posture("Sit", 0.5, 2) is True
    assert stub_qi.calls == [
        ("ALRobotPosture", "setMaxTryNumber", (2,)),
        ("ALRobotPosture", "goToPosture", ("Sit", 0.5)),
    ]


def test_real_backend_stops_a_posture_move(stub_qi: type[StubSession]):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    robot.stop_posture()
    assert stub_qi.calls == [("ALRobotPosture", "stopMove", ())]


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


def _speaking_robot(
    stub_qi: type[StubSession], speech: _AnimatedSpeech
) -> RealNaoqiRobot:
    robot = RealNaoqiRobot("127.0.0.1")
    robot.connect()
    robot._services["ALAnimatedSpeech"] = speech  # pyright: ignore[reportPrivateUsage]
    return robot


def test_stop_speech_ends_a_say_at_once_and_the_say_returns(
    stub_qi: type[StubSession],
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


def test_a_say_naoqi_fails_without_a_stop_still_raises(stub_qi: type[StubSession]):
    robot = _speaking_robot(stub_qi, _AnimatedSpeech(fails_with="no voice"))
    robot.stop_speech()  # a stop before this say does not excuse its failure
    with pytest.raises(RuntimeError, match="no voice"):
        robot.say("hello")
