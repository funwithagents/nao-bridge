"""Live: the verbs that move the robot, on the target.

Every test needs `room_to_move`: always on a sim; on a robot, NAOQI_E2E_ALLOW_MOTION=1
once the floor around it is clear and someone stays next to it. Every test wakes the
robot and leaves it at rest. Dances, body actions and apps run where the robot's
catalog holds one.
"""

import asyncio
import time

import pytest
from support import (
    app_behavior,
    behavior_running,
    dance_behavior,
    first_app,
    first_body_action,
    first_dance,
    wait_until,
)

from naoqi_bridge import MotorsOffError
from naoqi_bridge.testing import live_config, live_session

pytestmark = pytest.mark.requires("room_to_move")


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


@pytest.mark.requires("body_actions")
def test_a_body_action_and_a_reaction_run_to_their_end():
    async def run() -> tuple[tuple[str, ...], dict[str, str]]:
        async with live_session(live_config(), motion=True) as bridge:
            action_id = first_body_action(bridge)
            await bridge.stand_up()
            await bridge.body_action(action_id)
            await bridge.expressive_reaction("Happy")
            return bridge.current_body_actions, dict(
                bridge.current_expressive_reactions
            )

    assert asyncio.run(run()) == ((), {})


@pytest.mark.requires("dances")
def test_stop_dance_ends_a_dance_and_its_verb_returns():
    async def run() -> tuple[float, bool, tuple[str, ...]]:
        async with live_session(live_config(), motion=True) as bridge:
            dance_id = first_dance(bridge)
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


@pytest.mark.requires("apps")
def test_stop_app_ends_an_app_and_its_verb_returns():
    async def run() -> tuple[float, bool, tuple[str, ...]]:
        async with live_session(live_config(), motion=True) as bridge:
            app_id = first_app(bridge)
            behavior = app_behavior(bridge, app_id)
            running = asyncio.create_task(bridge.run_app(app_id))
            await wait_until(lambda: behavior_running(bridge, behavior))
            await asyncio.sleep(1.0)
            started = time.monotonic()
            await bridge.stop_app(app_id)
            async with asyncio.timeout(5.0):
                await running  # ends normally: stopped, not cancelled
            elapsed = time.monotonic() - started
            return elapsed, behavior_running(bridge, behavior), bridge.current_apps

    elapsed, still_running, tracked = asyncio.run(run())
    assert elapsed < 2.0
    assert not still_running
    assert tracked == ()
