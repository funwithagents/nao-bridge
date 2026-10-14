"""Backend selection in the robot seam (specs/robot.md)."""

import pytest

from naoqi_bridge.config import NaoqiBridgeConfig, RobotSettings
from naoqi_bridge.fake_robot import FakeNaoqiRobot
from naoqi_bridge.real_robot import RealNaoqiRobot
from naoqi_bridge.robot import build_robot
from naoqi_bridge.sim_robot import SimNaoqiRobot


def test_build_robot_follows_the_config():
    assert isinstance(build_robot(NaoqiBridgeConfig()), FakeNaoqiRobot)
    config = NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(ip="10.0.0.5", port=9600, connect_timeout_s=2.5),
    )
    real = build_robot(config)
    assert isinstance(real, RealNaoqiRobot)
    assert (real.ip, real.port, real.connect_timeout_s) == ("10.0.0.5", 9600, 2.5)


def test_fake_ignores_the_robot_block():
    config = NaoqiBridgeConfig(backend="fake", robot=RobotSettings(ip="10.0.0.5"))
    assert isinstance(build_robot(config), FakeNaoqiRobot)


def test_sim_connects_to_naoqi_sims_fixed_address():
    # On sim, the robot block's address is ignored: naoqi-sim always serves
    # 127.0.0.1:9559; the connection timeout still applies (specs/sim.md).
    config = NaoqiBridgeConfig(
        backend="sim",
        robot=RobotSettings(ip="10.0.0.5", port=9600, connect_timeout_s=2.5),
    )
    sim = build_robot(config)
    assert isinstance(sim, SimNaoqiRobot)
    assert (sim.ip, sim.port, sim.connect_timeout_s) == ("127.0.0.1", 9559, 2.5)


@pytest.mark.parametrize(
    ("sim", "through_crouch"),
    [
        ({}, False),  # naoqi-sim's default, 2.1
        ({"config": {"naoqi": {"version": "2.1"}}}, False),
        ({"config": {"naoqi": {"version": "2.8"}}}, True),
    ],
)
def test_only_the_2_8_sim_sits_through_crouch(sim: dict, through_crouch: bool):
    # NAOqi 2.8's desktop robot can't sit from Stand (specs/sim.md).
    robot = build_robot(NaoqiBridgeConfig.from_dict({"backend": "sim", "sim": sim}))
    assert isinstance(robot, SimNaoqiRobot)
    assert robot.sit_through_crouch is through_crouch
