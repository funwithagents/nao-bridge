"""``SimNaoqiRobot``: the ``sim`` backend's robot (specs/robot.md, specs/sim.md).

A naoqi-sim is a Naoqi like any other, so this is ``RealNaoqiRobot`` at naoqi-sim's
fixed address. Starting, borrowing and stopping the sim are the bridge's
(``sim.py``), not the robot's. The one difference in behavior is sitting on NAOqi 2.8.
"""

from __future__ import annotations

import threading

from .real_robot import RealNaoqiRobot
from .sim import SIM_HOST, SIM_PORT

__all__ = ["SimNaoqiRobot"]


class SimNaoqiRobot(RealNaoqiRobot):
    """A naoqi-sim over ``qi``, at ``SIM_HOST:SIM_PORT``."""

    def __init__(
        self, *, connect_timeout_s: float = 5.0, sit_through_crouch: bool = False
    ) -> None:
        super().__init__(SIM_HOST, SIM_PORT, connect_timeout_s=connect_timeout_s)
        # Reach Sit from Crouch and judge it by getPosture(): the 2.8 desktop robot
        # can't sit otherwise (specs/sim.md, "What a sim offers the bridge").
        self.sit_through_crouch = sit_through_crouch
        self._posture_stopped = threading.Event()

    def go_to_posture(self, posture: str, speed: float, max_tries: int) -> bool:
        if not (self.sit_through_crouch and posture == "Sit"):
            return super().go_to_posture(posture, speed, max_tries)
        # NAOqi 2.8's desktop robot has no inertial sensor: its posture manager takes
        # the lean of Stand -> Sit for a push and stays standing, and from Crouch it
        # reaches Sit but often reports it didn't. So: through Crouch, then ask.
        robot_posture = self._service("ALRobotPosture")
        robot_posture.setMaxTryNumber(max_tries)
        self._posture_stopped.clear()
        if robot_posture.getPosture() != "Crouch":
            robot_posture.goToPosture("Crouch", speed)
            if self._posture_stopped.is_set():
                return False
        robot_posture.goToPosture("Sit", speed)
        return robot_posture.getPosture() == "Sit"

    def stop_posture(self) -> None:
        self._posture_stopped.set()  # a stop between the two legs ends the move too
        super().stop_posture()
