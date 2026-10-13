"""Helpers for the opt-in live tier.

A live test needs real credentials. Rather than fail when they're absent, a test
calls `require_env(...)` up front so it *skips* cleanly — you only exercise the
services you hold keys for, and a contributor (or CI) with none is never broken.

Here the service is a real Nao, and the tier has three levels of risk
(specs/testing.md "Live tier: levels of risk"): safe (`NAO_IP`), motion
(`NAO_ALLOW_MOTION=1`) and interactive (`NAO_INTERACTIVE=1`).
"""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from naoqi_bridge import NaoqiBridge, NaoqiBridgeConfig, RobotSettings, StreamSettings
from naoqi_bridge.real_robot import RealNaoRobot

logger = logging.getLogger("live")

# (label, value) measured on the robot — cancel latencies, the audio chunk size —
# printed in the run's terminal summary.
MEASUREMENTS: list[tuple[str, str]] = []

# What a cancel may take on the robot before a test calls it slow: one stop call and
# the robot call's return, well inside the bridge's 4 × 0.5 s give-up bound.
CANCEL_BOUND_S = 2.0

# What the bridge logs when a cancelled verb's stop didn't go as planned.
STOP_WARNINGS = ("did not confirm the stop", "stopping it failed")


def require_env(name: str) -> str:
    """Return env var `name`, or skip the calling test if it's unset/empty."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set; skipping live test")
    return value


def require_flag(name: str) -> None:
    """Skip the calling test unless env var `name` is `1`, `true` or `yes`."""
    if os.environ.get(name, "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip(f"{name} not set to 1; skipping live test")


def live_config(streams: StreamSettings | None = None) -> NaoqiBridgeConfig:
    """A `real` bridge config for the robot at `NAO_IP` (skips when it's unset)."""
    ip = require_env("NAO_IP")
    port = int(os.environ.get("NAO_PORT", "9559"))
    return NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(ip=ip, port=port),
        streams=streams or StreamSettings(),
    )


@contextlib.asynccontextmanager
async def live_session(
    config: NaoqiBridgeConfig, *, motion: bool = False
) -> AsyncIterator[NaoqiBridge]:
    """A running bridge on the robot, left as it was found: eyes white and, at the
    motion level (motors woken on entry), at rest."""
    if motion:
        require_flag("NAO_ALLOW_MOTION")
    async with NaoqiBridge(config) as bridge:
        try:
            if motion:
                await bridge.wake_up()
            yield bridge
        finally:
            restore: list[Callable[[], Awaitable[None]]] = [
                lambda: bridge.change_eyes_color("white")
            ]
            if motion:
                restore.append(bridge.rest)
            for step in restore:
                try:
                    await step()
                except Exception:
                    logger.exception("Restoring the robot failed")


def first_dance(bridge: NaoqiBridge) -> str:
    dances = bridge.get_dance_behaviors()
    if not dances:
        pytest.skip("this robot has no dance installed")
    return dances[0].id


def first_body_action(bridge: NaoqiBridge) -> str:
    actions = bridge.get_body_action_behaviors()
    if not actions:
        pytest.skip("this robot has no body action installed")
    return actions[0].id


def dance_behavior(bridge: NaoqiBridge, dance_id: str) -> str:
    return next(
        d.behavior_name for d in bridge.get_dance_behaviors() if d.id == dance_id
    )


def body_action_behavior(bridge: NaoqiBridge, action_id: str) -> str:
    return next(
        a.behavior_name for a in bridge.get_body_action_behaviors() if a.id == action_id
    )


def naoqi(bridge: NaoqiBridge, service: str) -> object:
    """A Naoqi service, for a test that wants the robot's own view of its state."""
    robot = bridge.robot
    assert isinstance(robot, RealNaoRobot)
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
