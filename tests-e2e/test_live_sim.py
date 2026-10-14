"""Live: the sim backend itself (specs/sim.md), against the session's naoqi-sim. What
only a running naoqi-sim shows: borrowing it leaves it running, and a config that asks
for a sim of its own or another version is refused. Skipped on a robot."""

import asyncio

import naoqi_sim
import pytest
from support import SIM_VERSION, SIM_VERSIONS, TARGET

from naoqi_bridge import NaoqiBridge, NaoqiBridgeConfig, RobotConnectionError
from naoqi_bridge.config import SimSpawn

pytest.importorskip("qi")


@pytest.fixture(autouse=True)
def sim_target_only() -> None:
    if TARGET != "sim":
        pytest.skip("tests the sim backend: NAOQI_E2E_TARGET is not sim")


def sim_bridge(spawn: SimSpawn, version: str = SIM_VERSION) -> NaoqiBridge:
    return NaoqiBridge(
        NaoqiBridgeConfig.from_dict(
            {
                "backend": "sim",
                "sim": {"spawn": spawn, "config": {"naoqi": {"version": version}}},
            }
        )
    )


def test_auto_borrows_the_running_sim_and_leaves_it_running():
    async def run() -> bool:
        async with sim_bridge("auto") as bridge:
            await bridge.change_eyes_color("blue")
            await bridge.change_eyes_color("white")
        return (await naoqi_sim.read_status()).ready

    assert asyncio.run(run())


def test_always_refuses_a_sim_already_running():
    with pytest.raises(RobotConnectionError, match="already runs"):
        asyncio.run(sim_bridge("always").start())


def test_a_config_of_the_other_version_is_refused():
    other = next(v for v in SIM_VERSIONS if v != SIM_VERSION)
    bridge = sim_bridge("auto", other)
    with pytest.raises(RobotConnectionError, match=f"not {other}"):
        asyncio.run(bridge.start())
    assert not bridge.running
