"""Live checks against a real Nao: skipped unless NAO_IP is set and `qi` is installed.

Run explicitly: `NAO_IP=192.168.1.42 uv run pytest tests-e2e`. Nothing here moves the
robot's limbs; it connects, reads the catalog, and blinks the eyes.
"""

import asyncio
import os

import pytest
from support import require_env

from nao_bridge import NaoBridge

pytest.importorskip("qi")


def test_connects_and_reads_a_catalog():
    ip = require_env("NAO_IP")
    port = int(os.environ.get("NAO_PORT", "9559"))

    async def run() -> tuple[int, bool, bool]:
        async with NaoBridge("real", ip=ip, port=port) as bridge:
            colored = await bridge.change_eyes_color("blue")
            restored = await bridge.change_eyes_color("white")
            return len(bridge.get_body_action_behaviors()), colored, restored

    body_actions, colored, restored = asyncio.run(run())
    assert colored and restored
    # Any stock Nao ships at least the dialog_move_arms actions.
    assert body_actions > 0
