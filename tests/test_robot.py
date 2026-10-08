"""The robot seam (specs/robot.md): backend selection, the real backend's connection
rules (with a stub ``qi`` module), and the fake's behavior-run and sensor simulation.

No robot, network or real ``qi`` needed. Async runs via ``asyncio.run``.
"""

import sys
import threading
import types
from typing import Any, ClassVar

import pytest

from nao_bridge.robot import (
    FakeNaoRobot,
    QiNaoRobot,
    RobotConnectionError,
    build_robot,
)


def test_build_robot_selects_the_backend():
    assert isinstance(build_robot("fake"), FakeNaoRobot)
    real = build_robot("real", ip="10.0.0.5", port=9600)
    assert isinstance(real, QiNaoRobot)
    assert (real.ip, real.port) == ("10.0.0.5", 9600)


def test_build_robot_rejects_an_unknown_backend():
    with pytest.raises(ValueError, match="sim"):
        build_robot("sim")  # type: ignore[arg-type]


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


class _StubSession:
    """Stands in for ``qi.Session``: fails the first ``failures`` connects."""

    failures: ClassVar[int] = 0
    connects: ClassVar[int] = 0
    calls: ClassVar[list[tuple[str, str, tuple[Any, ...]]]] = []

    def connect(self, url: str) -> None:
        type(self).connects += 1
        if type(self).connects <= type(self).failures:
            raise RuntimeError(f"cannot reach {url}")

    def service(self, name: str) -> _StubService:
        return _StubService(type(self).calls, name)

    def close(self) -> None:
        pass


@pytest.fixture
def stub_qi(monkeypatch: pytest.MonkeyPatch) -> type[_StubSession]:
    _StubSession.failures = 0
    _StubSession.connects = 0
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
    robot.say("hello")
    assert stub_qi.calls == [("ALAnimatedSpeech", "say", ("hello",))]


def test_real_backend_gives_up_after_its_tries(stub_qi: type[_StubSession]):
    stub_qi.failures = QiNaoRobot.CONNECT_TRIES
    with pytest.raises(RobotConnectionError, match="after 10 tries") as caught:
        QiNaoRobot("10.0.0.5").connect()
    assert isinstance(caught.value.__cause__, RuntimeError)


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
