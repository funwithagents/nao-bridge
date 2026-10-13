"""Backend selection in the robot seam (specs/robot.md)."""

from naoqi_bridge.config import NaoqiBridgeConfig, RobotSettings
from naoqi_bridge.fake_robot import FakeNaoqiRobot
from naoqi_bridge.naoqi_robot import NaoqiRobot
from naoqi_bridge.robot import build_robot


def test_build_robot_follows_the_config():
    assert isinstance(build_robot(NaoqiBridgeConfig()), FakeNaoqiRobot)
    config = NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(ip="10.0.0.5", port=9600, connect_timeout_s=2.5),
    )
    real = build_robot(config)
    assert isinstance(real, NaoqiRobot)
    assert (real.ip, real.port, real.connect_timeout_s) == ("10.0.0.5", 9600, 2.5)


def test_fake_ignores_the_robot_block():
    config = NaoqiBridgeConfig(backend="fake", robot=RobotSettings(ip="10.0.0.5"))
    assert isinstance(build_robot(config), FakeNaoqiRobot)
