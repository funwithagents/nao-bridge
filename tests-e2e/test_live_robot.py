"""Live checks against a real Nao: skipped unless NAOQI_E2E_IP is set and `qi` is installed.

Run explicitly: `NAOQI_E2E_IP=192.168.1.42 uv run pytest tests-e2e`. Nothing here moves the
robot's limbs; it connects, reads the catalog, and blinks the eyes.
"""

import asyncio
import os

import pytest
from support import require_env

from naoqi_bridge import NaoqiBridge, NaoqiBridgeConfig, RobotSettings

pytest.importorskip("qi")


def test_connects_and_reads_a_catalog():
    ip = require_env("NAOQI_E2E_IP")
    port = int(os.environ.get("NAOQI_E2E_PORT", "9559"))

    async def run() -> int:
        config = NaoqiBridgeConfig(
            backend="real", robot=RobotSettings(ip=ip, port=port)
        )
        async with NaoqiBridge(config) as bridge:
            # A verb the robot fails raises CommandFailedError, failing the test.
            await bridge.change_eyes_color("blue")
            await bridge.change_eyes_color("white")
            return len(bridge.get_body_action_behaviors())

    body_actions = asyncio.run(run())
    # Any stock Nao ships at least the dialog_move_arms actions.
    assert body_actions > 0
