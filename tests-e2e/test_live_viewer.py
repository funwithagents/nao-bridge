"""The bridge's viewer on the target (specs/viewer.md): its window opens with the
session, mirrors the robot, and closes with it.

Opt-in with `NAOQI_E2E_VIEWER=1`: a window needs a display, so it never runs in CI.
On the sim target the bridge borrows the session's sim, so it opens its own mirror.
"""

import asyncio
import dataclasses

import pytest
from support import live_config, require_flag, wait_until

from naoqi_bridge import NaoqiBridge, ViewerSettings

pytest.importorskip("qi")
pytest.importorskip("naoqi_viewer")


def test_the_viewer_opens_with_the_bridge_and_closes_with_it():
    require_flag("NAOQI_E2E_VIEWER")
    config = dataclasses.replace(live_config(), viewer=ViewerSettings(enabled=True))

    async def run() -> None:
        bridge = NaoqiBridge(config)
        await bridge.start()
        # The window itself is the bridge's own business; reach it to watch it.
        viewer = bridge._viewer
        try:
            assert viewer is not None and viewer.running
            await wait_until(lambda: viewer.status().data_age is not None)
        finally:
            await bridge.stop()
        assert not viewer.running

    asyncio.run(run())
