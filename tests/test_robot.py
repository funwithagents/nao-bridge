"""Backend selection in the robot seam (specs/robot.md)."""

from nao_bridge.config import NaoBridgeConfig, RobotSettings
from nao_bridge.fake_robot import FakeNaoRobot
from nao_bridge.real_robot import RealNaoRobot
from nao_bridge.robot import build_robot


def test_build_robot_follows_the_config():
    assert isinstance(build_robot(NaoBridgeConfig()), FakeNaoRobot)
    config = NaoBridgeConfig(
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
    config = NaoBridgeConfig(backend="fake", robot=RobotSettings(ip="10.0.0.5"))
    assert isinstance(build_robot(config), FakeNaoRobot)
