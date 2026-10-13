"""Live, motion level: the verbs that move the robot, on the target.

Always on a sim. On a robot, skipped unless NAOQI_E2E_ALLOW_MOTION=1: clear the floor
around the robot and stay next to it. Every test wakes the robot and leaves it at rest.
"""

import asyncio
import time

import pytest
from support import (
    behavior_running,
    dance_behavior,
    first_body_action,
    first_dance,
    live_config,
    live_session,
    wait_until,
)

from naoqi_bridge import MotorsOffError

pytest.importorskip("qi")


def test_wake_up_and_rest_switch_the_motors_and_the_motors_check_follows():
    async def run() -> tuple[bool, bool]:
        async with live_session(live_config(), motion=True) as bridge:
            awake = bridge.robot.is_awake()
            await bridge.rest()
            resting = not bridge.robot.is_awake()
            with pytest.raises(MotorsOffError):
                await bridge.stand_up()
            await bridge.wake_up()  # live_session rests the robot again at the end
            return awake, resting

    assert asyncio.run(run()) == (True, True)


def test_postures_and_breathing():
    async def run() -> None:
        async with live_session(live_config(), motion=True) as bridge:
            await bridge.stand_up()  # CommandFailedError if the posture isn't reached
            await bridge.sit_down()
            await bridge.stand_up()
            await bridge.set_breathing_enabled(True, "Body")
            await asyncio.sleep(2.0)
            await bridge.set_breathing_enabled(False, "Body")

    asyncio.run(run())


def test_a_body_action_and_a_reaction_run_to_their_end():
    async def run() -> tuple[tuple[str, ...], dict[str, str]]:
        async with live_session(live_config(), motion=True) as bridge:
            action_id = first_body_action(bridge)  # skips before the robot moves
            await bridge.stand_up()
            await bridge.body_action(action_id)
            await bridge.expressive_reaction("Happy")
            return bridge.current_body_actions, dict(
                bridge.current_expressive_reactions
            )

    assert asyncio.run(run()) == ((), {})


def test_stop_dance_ends_a_dance_and_its_verb_returns():
    async def run() -> tuple[float, bool, tuple[str, ...]]:
        async with live_session(live_config(), motion=True) as bridge:
            dance_id = first_dance(bridge)  # skips before the robot moves
            await bridge.stand_up()
            behavior = dance_behavior(bridge, dance_id)
            dancing = asyncio.create_task(bridge.dance(dance_id))
            await wait_until(lambda: behavior_running(bridge, behavior))
            await asyncio.sleep(2.0)
            started = time.monotonic()
            await bridge.stop_dance(dance_id)
            async with asyncio.timeout(5.0):
                await dancing  # ends normally: stopped, not cancelled
            elapsed = time.monotonic() - started
            return elapsed, behavior_running(bridge, behavior), bridge.current_dances

    elapsed, still_running, tracked = asyncio.run(run())
    assert elapsed < 2.0
    assert not still_running
    assert tracked == ()
