"""Live checks against the target (a sim by default, or the robot at NAOQI_E2E_IP).

Run explicitly: `uv run pytest tests-e2e`. Nothing here moves the robot's limbs; it
connects, reads the catalog, and blinks the eyes.
"""

import asyncio

import pytest
from support import TARGET, live_config

from naoqi_bridge import NaoqiBridge

pytest.importorskip("qi")


def test_connects_and_reads_a_catalog():
    config = live_config()

    async def run() -> int:
        async with NaoqiBridge(config) as bridge:
            # A verb the robot fails raises CommandFailedError, failing the test.
            await bridge.change_eyes_color("blue")
            await bridge.change_eyes_color("white")
            return len(bridge.get_body_action_behaviors())

    body_actions = asyncio.run(run())
    if TARGET == "real":
        # Any stock Nao ships at least the dialog_move_arms actions; a sim has the
        # animations package only (specs/sim.md).
        assert body_actions > 0
