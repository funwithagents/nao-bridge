"""Helpers of the bridge's own live tier, next to the shipped harness
(`naoqi_bridge.testing`, specs/testing_support.md), which owns the target, its
capabilities and `live_config` / `live_session`.

Here: what the tier measures (cancel latencies, the audio chunk size), the catalog
pickers, and reads of Naoqi's own state through `bridge.robot`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import pytest

from naoqi_bridge import NaoqiBridge
from naoqi_bridge.real_robot import RealNaoqiRobot

# (label, value) measured on the robot — cancel latencies, the audio chunk size —
# printed in the run's terminal summary.
MEASUREMENTS: list[tuple[str, str]] = []

# What a cancel may take on the robot before a test calls it slow: NAOqi's own end of
# the stopped command (about 2.4 s for a posture move, measured on a simulated Nao) and one retry interval, inside the bridge's 8 × 0.5 s
# give-up bound.
CANCEL_BOUND_S = 3.5

# What the bridge logs when a cancelled verb's stop didn't go as planned.
STOP_WARNINGS = ("did not confirm the stop", "stopping it failed")


# region The catalog: the `dances`, `body_actions` and `apps` capabilities say it holds one


def first_dance(bridge: NaoqiBridge) -> str:
    return bridge.get_dance_behaviors()[0].id


def first_body_action(bridge: NaoqiBridge) -> str:
    return bridge.get_body_action_behaviors()[0].id


def first_app(bridge: NaoqiBridge) -> str:
    return bridge.get_app_behaviors()[0].id


def dance_behavior(bridge: NaoqiBridge, dance_id: str) -> str:
    return next(
        d.behavior_name for d in bridge.get_dance_behaviors() if d.id == dance_id
    )


def body_action_behavior(bridge: NaoqiBridge, action_id: str) -> str:
    return next(
        a.behavior_name for a in bridge.get_body_action_behaviors() if a.id == action_id
    )


def app_behavior(bridge: NaoqiBridge, app_id: str) -> str:
    return next(a.behavior_name for a in bridge.get_app_behaviors() if a.id == app_id)


# endregion


def naoqi(bridge: NaoqiBridge, service: str) -> object:
    """A Naoqi service, for a test that wants the robot's own view of its state."""
    robot = bridge.robot
    assert isinstance(robot, RealNaoqiRobot)
    return robot._service(service)  # pyright: ignore[reportPrivateUsage]


def behavior_running(bridge: NaoqiBridge, behavior_name: str) -> bool:
    manager = naoqi(bridge, "ALBehaviorManager")
    return bool(manager.isBehaviorRunning(behavior_name))  # pyright: ignore[reportAttributeAccessIssue]


async def wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    """Poll ``predicate()`` until it holds, failing the test after ``timeout`` s."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


async def measure_cancel(label: str, task: asyncio.Task[None]) -> float:
    """Cancel ``task``, check it ends cancelled, record and return how long that took."""
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    elapsed = time.monotonic() - started
    MEASUREMENTS.append((f"cancel {label}", f"{elapsed * 1000:.0f} ms"))
    return elapsed


def stop_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The bridge's warnings about a stop that didn't go as planned."""
    return [m for m in caplog.messages if any(w in m for w in STOP_WARNINGS)]
