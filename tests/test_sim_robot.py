"""The sim backend's robot (specs/robot.md, specs/sim.md): ``RealNaoqiRobot`` at
naoqi-sim's address, sitting through Crouch on a 2.8 sim. Against the stub ``qi``
module (tests/qi_stub.py)."""

import threading
import time

import pytest
from qi_stub import StubSession

from naoqi_bridge.real_robot import RealNaoqiRobot
from naoqi_bridge.sim_robot import SimNaoqiRobot


def test_the_sim_robot_is_a_naoqi_robot_at_naoqi_sims_address():
    robot = SimNaoqiRobot(connect_timeout_s=2.5)
    assert isinstance(robot, RealNaoqiRobot)
    assert (robot.ip, robot.port, robot.connect_timeout_s) == ("127.0.0.1", 9559, 2.5)


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


def _robot_on(posture: _Posture28, *, sit_through_crouch: bool) -> SimNaoqiRobot:
    robot = SimNaoqiRobot(sit_through_crouch=sit_through_crouch)
    robot.connect()
    robot._services["ALRobotPosture"] = posture  # pyright: ignore[reportPrivateUsage]
    return robot


def test_sit_is_asked_directly_and_its_result_trusted_by_default(
    stub_qi: type[StubSession],
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
    stub_qi: type[StubSession], start: str, moves: list[str]
):
    posture = _Posture28(start)
    robot = _robot_on(posture, sit_through_crouch=True)
    # goToPosture("Sit") reports False, yet the robot sits: success.
    assert robot.go_to_posture("Sit", 0.8, 3) is True
    assert (posture.moves, posture.posture) == (moves, "Sit")
    # Other postures are asked for directly, as on any Naoqi.
    assert robot.go_to_posture("Stand", 0.8, 3) is True
    assert posture.moves[-1:] == ["Stand"] and len(posture.moves) == len(moves) + 1


def test_a_stop_during_the_crouch_leg_ends_the_sit(stub_qi: type[StubSession]):
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
