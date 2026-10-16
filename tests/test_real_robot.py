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
    robot.subscribe_posture(lambda key, value: None)
    robot.subscribe_audio(lambda *_: None, "front")
    robot.close()
    stub_qi.calls.clear()
    # Nothing left to release: no disconnect, no unregister, and no error either.
    robot.unsubscribe_touch()
    robot.unsubscribe_posture()
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


def test_real_backend_reads_the_posture_and_its_family(stub_qi: type[StubSession]):
    stub_qi.returns = {
        ("ALRobotPosture", "getPosture"): "Sit",
        ("ALRobotPosture", "getPostureFamily"): "Sitting",
    }
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    assert robot.get_posture() == ("Sit", "Sitting")


def test_real_backend_follows_naoqis_posture_events_until_unsubscribed(
    stub_qi: type[StubSession],
):
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    robot.subscribe_posture(lambda key, value: None)
    robot.unsubscribe_posture()
    robot.unsubscribe_posture()  # nothing left to release
    assert stub_qi.calls == [
        ("ALMemory", "connect", ("PostureChanged",)),
        ("ALMemory", "connect", ("PostureFamilyChanged",)),
        ("ALMemory", "disconnect", ("PostureChanged",)),
        ("ALMemory", "disconnect", ("PostureFamilyChanged",)),
    ]


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


# --- Cameras (specs/camera.md "The seam") ---

TRANSFORM = [float(i) for i in range(16)]


def _image(ts_s: int = 12, ts_us: int = 500000) -> list[Any]:
    """An ALVideoDevice image: width, height, layers, colorspace, ts_s, ts_us, buffer,
    camera id, left, top, right, bottom angles."""
    return [2, 1, 3, 13, ts_s, ts_us, bytearray(range(6)), 0, 0.5, 0.4, -0.5, -0.4]


def _camera_robot(stub_qi: type[StubSession]) -> RealNaoqiRobot:
    stub_qi.returns[("ALVideoDevice", "unsubscribe")] = False  # no stale handle
    stub_qi.returns[("ALVideoDevice", "subscribeCamera")] = "NaoqiBridgeCameraTop_0"
    stub_qi.returns[("ALVideoDevice", "getImageRemote")] = _image()
    stub_qi.returns[("ALMotion", "getTransform")] = TRANSFORM
    robot = RealNaoqiRobot("10.0.0.5")
    robot.connect()
    return robot


def test_subscribing_a_camera_clears_stale_handles_then_asks_for_bgr(
    stub_qi: type[StubSession],
):
    robot = _camera_robot(stub_qi)
    robot.subscribe_camera("bottom", "vga", 15)
    assert stub_qi.calls == [
        *(
            ("ALVideoDevice", "unsubscribe", (f"NaoqiBridgeCameraBottom_{n}",))
            for n in range(7)
        ),
        ("ALVideoDevice", "subscribeCamera", ("NaoqiBridgeCameraBottom", 1, 2, 13, 15)),
    ]


def test_a_camera_naoqi_refuses_to_subscribe_raises(stub_qi: type[StubSession]):
    robot = _camera_robot(stub_qi)
    stub_qi.returns[("ALVideoDevice", "subscribeCamera")] = ""
    with pytest.raises(RuntimeError, match="NaoqiBridgeCameraTop"):
        robot.subscribe_camera("top", "qvga", 10)


def test_reading_a_camera_pulls_the_image_then_the_pose_then_releases(
    stub_qi: type[StubSession],
):
    robot = _camera_robot(stub_qi)
    robot.subscribe_camera("top", "qvga", 10)
    stub_qi.calls.clear()
    read = robot.read_camera("top")
    assert stub_qi.calls == [
        ("ALVideoDevice", "getImageRemote", ("NaoqiBridgeCameraTop_0",)),
        ("ALMotion", "getTransform", ("CameraTop", 2, True)),
        ("ALVideoDevice", "releaseImage", ("NaoqiBridgeCameraTop_0",)),
    ]
    assert read is not None
    assert (read.width, read.height) == (2, 1)
    assert read.data == bytes(range(6))
    assert read.naoqi_ts == 12.5
    assert read.fov == pytest.approx((1.0, 0.8))
    assert read.transform == tuple(TRANSFORM)


def test_a_camera_that_returns_no_image_reads_as_none(stub_qi: type[StubSession]):
    robot = _camera_robot(stub_qi)
    stub_qi.returns[("ALVideoDevice", "getImageRemote")] = None
    robot.subscribe_camera("top", "qvga", 10)
    assert robot.read_camera("top") is None


def test_unsubscribing_a_camera_gives_its_handle_back_once(
    stub_qi: type[StubSession],
):
    robot = _camera_robot(stub_qi)
    robot.subscribe_camera("top", "qvga", 10)
    stub_qi.calls.clear()
    robot.unsubscribe_camera("top")
    robot.unsubscribe_camera("top")
    assert stub_qi.calls == [
        ("ALVideoDevice", "unsubscribe", ("NaoqiBridgeCameraTop_0",))
    ]
    with pytest.raises(RuntimeError, match="not subscribed"):
        robot.read_camera("top")


def test_close_unsubscribes_the_cameras_still_held(stub_qi: type[StubSession]):
    robot = _camera_robot(stub_qi)
    robot.subscribe_camera("top", "qvga", 10)
    stub_qi.calls.clear()
    robot.close()
    assert stub_qi.calls == [
        ("ALVideoDevice", "unsubscribe", ("NaoqiBridgeCameraTop_0",))
    ]
    assert stub_qi.closed == 1


def test_camera_calls_while_disconnected_raise(stub_qi: type[StubSession]):
    robot = RealNaoqiRobot("10.0.0.5")
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.subscribe_camera("top", "qvga", 10)
    with pytest.raises(RobotConnectionError, match="not connected"):
        robot.read_camera("top")
    assert stub_qi.calls == []
