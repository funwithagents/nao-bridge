"""Live checks against the target (a sim by default, or the robot at NAOQI_E2E_IP).

Run explicitly: `uv run pytest tests-e2e`. Nothing here moves the robot's limbs; it
connects, reads the catalog, and blinks the eyes.
"""

import asyncio

from naoqi_bridge import NaoqiBridge
from naoqi_bridge.testing import live_config


def test_connects_and_reads_a_catalog():
    config = live_config()

    async def run() -> list[str]:
        async with NaoqiBridge(config) as bridge:
            # A verb the robot fails raises CommandFailedError, failing the test.
            await bridge.change_eyes_color("blue")
            await bridge.change_eyes_color("white")
            return bridge.get_expressive_reaction_types()

    # Every Naoqi the bridge targets holds the `animations` package's reactions; what
    # else its catalog holds (dances, body actions, apps) is a capability.
    assert "Happy" in asyncio.run(run())
