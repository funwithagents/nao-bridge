"""Live: the cancellation contract (specs/bridge.md "Cancellation") on the target.

A cancelled verb must come back quickly with the robot stopped, the bridge's tracking
empty, no stop warning logged, and the session ready for the next verb. Each cancel's
latency is printed in the run's summary.

On any target: a cancelled `say`, and a cancelled `start()` (which needs `qi` only).
With `room_to_move` (always on a sim; NAOQI_E2E_ALLOW_MOTION=1 on a robot): postures and
reactions, and the dances, body actions and apps the robot's catalog holds.
"""

import asyncio
import logging
import time
from collections.abc import Callable

import pytest
from support import (
    CANCEL_BOUND_S,
    MEASUREMENTS,
    app_behavior,
    behavior_running,
    body_action_behavior,
    dance_behavior,
    first_app,
    first_body_action,
    first_dance,
    measure_cancel,
    stop_warnings,
    wait_until,
)

from naoqi_bridge import NaoqiBridge, NaoqiBridgeConfig, RobotSettings
from naoqi_bridge.testing import live_config, live_session

LONG_SENTENCE = (
    "I am going to talk for quite a while now, so that the test has all the time "
    "it needs to cancel me somewhere in the middle of this very long sentence."
)


@pytest.fixture(autouse=True)
def bridge_warnings(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="naoqi_bridge.bridge")


# --- Any target ---------------------------------------------------------------


def test_a_cancelled_say_stops_the_speech(caplog: pytest.LogCaptureFixture):
    async def run() -> float:
        async with live_session(live_config()) as bridge:
            await bridge.set_tts_language("English")
            saying = asyncio.create_task(bridge.say(LONG_SENTENCE))
            await asyncio.sleep(1.0)
            elapsed = await measure_cancel("say", saying)
            await bridge.say("And I can talk again.")  # the session is usable
            return elapsed

    assert asyncio.run(run()) < CANCEL_BOUND_S
    assert stop_warnings(caplog) == []


def test_a_start_cancelled_while_connecting_comes_back_not_running():
    # A non-routable address: the attempt would run into its timeout. Needs qi, no robot.
    config = NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(ip="10.255.255.1", connect_timeout_s=10.0),
    )

    async def run() -> tuple[float, bool]:
        bridge = NaoqiBridge(config)
        starting = asyncio.create_task(bridge.start())
        await asyncio.sleep(0.3)
        started = time.monotonic()
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        elapsed = time.monotonic() - started
        MEASUREMENTS.append(
            ("cancel start() mid-connection", f"{elapsed * 1000:.0f} ms")
        )
        return elapsed, bridge.running

    elapsed, running = asyncio.run(run())
    assert not running
    # The attempt in flight is given up, not waited out (specs/bridge.md).
    assert elapsed < 1.0


# --- Motion -------------------------------------------------------------------


async def cancel_behavior_verb(
    bridge: NaoqiBridge,
    label: str,
    verb: asyncio.Task[None],
    behavior_name: str,
    tracked: Callable[[], object],
    after_s: float,
) -> float:
    """Wait until ``verb`` is tracked; with ``after_s``, also until the robot runs
    ``behavior_name``, plus ``after_s`` s. Then cancel it and check the robot really
    stopped it."""
    await wait_until(lambda: bool(tracked()))
    if after_s:
        await wait_until(lambda: behavior_running(bridge, behavior_name))
        await asyncio.sleep(after_s)
    elapsed = await measure_cancel(label, verb)
    assert not behavior_running(bridge, behavior_name)
    assert not tracked()
    return elapsed


@pytest.mark.requires("room_to_move", "dances")
@pytest.mark.parametrize("after_s", [2.0, 0.0], ids=["mid-dance", "at-once"])
def test_a_cancelled_dance_stops_on_the_robot(
    after_s: float, caplog: pytest.LogCaptureFixture
):
    async def run() -> float:
        async with live_session(live_config(), motion=True) as bridge:
            dance_id = first_dance(bridge)
            await bridge.stand_up()
            behavior = dance_behavior(bridge, dance_id)
            dancing = asyncio.create_task(bridge.dance(dance_id))
            elapsed = await cancel_behavior_verb(
                bridge,
                f"dance ({'at once' if not after_s else 'mid-dance'})",
                dancing,
                behavior,
                lambda: bridge.current_dances,
                after_s,
            )
            await bridge.stand_up()  # the session is usable, and the robot steady
            return elapsed

    assert asyncio.run(run()) < CANCEL_BOUND_S
    assert stop_warnings(caplog) == []


@pytest.mark.requires("room_to_move", "body_actions")
def test_a_cancelled_body_action_stops_on_the_robot(caplog: pytest.LogCaptureFixture):
    async def run() -> float:
        async with live_session(live_config(), motion=True) as bridge:
            action_id = first_body_action(bridge)
            await bridge.stand_up()
            moving = asyncio.create_task(bridge.body_action(action_id))
            return await cancel_behavior_verb(
                bridge,
                "body action",
                moving,
                body_action_behavior(bridge, action_id),
                lambda: bridge.current_body_actions,
                0.5,
            )

    assert asyncio.run(run()) < CANCEL_BOUND_S
    assert stop_warnings(caplog) == []


@pytest.mark.requires("room_to_move", "apps")
def test_a_cancelled_app_stops_on_the_robot(caplog: pytest.LogCaptureFixture):
    async def run() -> float:
        async with live_session(live_config(), motion=True) as bridge:
            app_id = first_app(bridge)
            running = asyncio.create_task(bridge.run_app(app_id))
            return await cancel_behavior_verb(
                bridge,
                "app",
                running,
                app_behavior(bridge, app_id),
                lambda: bridge.current_apps,
                1.0,
            )

    assert asyncio.run(run()) < CANCEL_BOUND_S
    assert stop_warnings(caplog) == []


@pytest.mark.requires("room_to_move")
def test_a_timeout_around_a_reaction_stops_it(caplog: pytest.LogCaptureFixture):
    async def run() -> tuple[float, bool]:
        async with live_session(live_config(), motion=True) as bridge:
            await bridge.stand_up()
            playing: list[str] = []

            async def note_the_pick() -> None:
                await wait_until(lambda: "Happy" in bridge.current_expressive_reactions)
                playing.append(bridge.current_expressive_reactions["Happy"])

            noting = asyncio.create_task(note_the_pick())
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(1.0):
                    await bridge.expressive_reaction("Happy")
            elapsed = time.monotonic() - started - 1.0  # past the timeout firing
            await noting
            MEASUREMENTS.append(
                ("cancel reaction (timeout)", f"{elapsed * 1000:.0f} ms")
            )
            return elapsed, behavior_running(bridge, playing[0])

    elapsed, still_running = asyncio.run(run())
    assert elapsed < CANCEL_BOUND_S
    assert not still_running
    assert stop_warnings(caplog) == []


@pytest.mark.requires("room_to_move")
def test_a_cancelled_stand_up_stops_the_move(caplog: pytest.LogCaptureFixture):
    async def run() -> tuple[float, float]:
        async with live_session(live_config(), motion=True) as bridge:
            await bridge.sit_down()
            standing = asyncio.create_task(bridge.stand_up())
            await asyncio.sleep(0.7)  # mid-move: watch the robot's balance here
            elapsed = await measure_cancel("stand_up", standing)
            # Stopped: the commanded angles no longer change.
            _, before = bridge.robot.get_joints()
            await asyncio.sleep(0.5)
            _, after = bridge.robot.get_joints()
            drift = max(abs(a - b) for a, b in zip(before, after, strict=True))
            await bridge.stand_up()  # the session is usable: finish the move
            return elapsed, drift

    elapsed, drift = asyncio.run(run())
    assert elapsed < CANCEL_BOUND_S
    assert drift < 0.02  # radians
    assert stop_warnings(caplog) == []
