"""Backend selection in the robot seam (specs/robot.md)."""

from naoqi_bridge.config import NaoqiBridgeConfig, RobotSettings
from naoqi_bridge.fake_robot import FakeNaoRobot
from naoqi_bridge.real_robot import RealNaoRobot
from naoqi_bridge.robot import build_robot


def test_build_robot_follows_the_config():
    assert isinstance(build_robot(NaoqiBridgeConfig()), FakeNaoRobot)
    config = NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(
            ip="10.0.0.5", port=9600, connect_tries=3, connect_timeout_s=2.5
        ),
    )
    real = build_robot(config)
    assert isinstance(real, RealNaoRobot)
    assert (real.ip, real.port, real.connect_tries, real.connect_timeout_s) == (
        "10.0.0.5",
        9600,
        3,
        2.5,
    )


def test_fake_ignores_the_robot_block():
    config = NaoqiBridgeConfig(backend="fake", robot=RobotSettings(ip="10.0.0.5"))
    assert isinstance(build_robot(config), FakeNaoRobot)
