"""Helpers for the opt-in live tier.

A live test needs real credentials. Rather than fail when they're absent, a test
calls `require_env(...)` up front so it *skips* cleanly — you only exercise the
services you hold keys for, and a contributor (or CI) with none is never broken.

Here the service is a Naoqi: a simulated Nao by default, or a real one
(specs/testing.md "Live tier: the target"), picked by `NAOQI_E2E_TARGET` (`sim` when
unset, `real`). On `sim`, one naoqi-sim serves the whole run (`NAOQI_E2E_SIM_VERSION`,
`NAOQI_E2E_SIM_VIEWER`): the first test that asks for the target starts it, or borrows
the one already running, through a bridge of its own on an event loop of its own;
`tests-e2e/conftest.py` stops it at the end of the run. The tier has three levels of
risk (specs/testing.md "Live tier: levels of risk"): safe (the target), motion
(`NAOQI_E2E_ALLOW_MOTION=1`, always on a sim) and interactive
(`NAOQI_E2E_INTERACTIVE=1`, skipped on a sim).
"""

import asyncio
import contextlib
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, NoReturn

import pytest

from naoqi_bridge import (
    NaoqiBridge,
    NaoqiBridgeConfig,
    RobotConnectionError,
    RobotSettings,
    SimSettings,
    StreamSettings,
)
from naoqi_bridge.config import ConfigError
from naoqi_bridge.naoqi_robot import NaoqiRobot

logger = logging.getLogger("live")

# (label, value) measured on the robot — cancel latencies, the audio chunk size —
# printed in the run's terminal summary.
MEASUREMENTS: list[tuple[str, str]] = []

# What a cancel may take on the robot before a test calls it slow: NAOqi's own end of
# the stopped command (up to about 2.5 s for a posture move or animated speech,
# measured on a simulated Nao) and one retry interval, inside the bridge's 8 × 0.5 s
# give-up bound.
CANCEL_BOUND_S = 3.5

# What the bridge logs when a cancelled verb's stop didn't go as planned.
STOP_WARNINGS = ("did not confirm the stop", "stopping it failed")


# region The target

TARGETS = ("sim", "real")
SIM_VERSIONS = ("2.1", "2.8")

# Set by name: then a sim that can't run fails the run instead of skipping it.
TARGET_REQUIRED = bool(os.environ.get("NAOQI_E2E_TARGET"))
TARGET = os.environ.get("NAOQI_E2E_TARGET") or "sim"
SIM_VERSION = os.environ.get("NAOQI_E2E_SIM_VERSION") or "2.1"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


SIM_VIEWER = _flag("NAOQI_E2E_SIM_VIEWER")


def check_target_settings() -> None:
    """Fail the session at once on a target or version the tier doesn't know."""
    if TARGET not in TARGETS:
        raise pytest.UsageError(
            f"NAOQI_E2E_TARGET={TARGET!r}: choose from {', '.join(TARGETS)}"
        )
    if SIM_VERSION not in SIM_VERSIONS:
        raise pytest.UsageError(
            f"NAOQI_E2E_SIM_VERSION={SIM_VERSION!r}: choose from {', '.join(SIM_VERSIONS)}"
        )


def sim_config() -> dict[str, Any]:
    """The run's sim, as a naoqi-sim config file holds it: headless with the render
    camera, the placeholder model, a silent loudspeaker and the fake microphone; or
    the window, with `NAOQI_E2E_SIM_VIEWER=1`."""
    viewer: dict[str, Any] = (
        {"headless": False}
        if SIM_VIEWER
        else {"headless": True, "variant": "placeholder"}
    )
    return {
        "naoqi": {"version": SIM_VERSION},
        "viewer": viewer,
        "video_input": {"source": "render"},
        "audio_output": {"mode": "silent"},
        "audio_input": {"source": "fake"},
    }


class _LoopThread:
    """An event loop running in its own thread, for a bridge that lives as long as
    the run: a bridge belongs to the loop that started it."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self.loop.run_forever, name="live-sim", daemon=True
        )
        self._thread.start()

    def run[T](self, coro: Awaitable[T]) -> T:
        async def wrapped() -> T:
            return await coro

        return asyncio.run_coroutine_threadsafe(wrapped(), self.loop).result()

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join()
        self.loop.close()


class _RunSim:
    """The run's sim: started (or borrowed) once, on first use; why it couldn't be,
    kept, so later tests don't try again."""

    def __init__(self) -> None:
        self._loop: _LoopThread | None = None
        self._owner: NaoqiBridge | None = None
        self._failure: str | None = None

    def require(self) -> None:
        if self._failure is None and self._owner is None:
            self._start()
        if self._failure is not None:
            _unavailable(self._failure)

    def _start(self) -> None:
        try:
            config = NaoqiBridgeConfig.from_dict(
                {"backend": "sim", "sim": {"spawn": "auto", "config": sim_config()}}
            )
        except ConfigError as e:  # no [sim] extra
            self._failure = str(e)
            return
        owner = NaoqiBridge(config)
        loop = _LoopThread()
        try:
            loop.run(owner.start())
        except RobotConnectionError as e:  # no Docker, no images, a port, a version
            loop.close()
            self._failure = str(e)
            return
        self._loop, self._owner = loop, owner
        logger.warning(
            "Live tier on a naoqi-sim, NAOqi %s (%s)",
            SIM_VERSION,
            "the window" if SIM_VIEWER else "headless",
        )

    def stop(self) -> None:
        """Stop the run's bridge, and with it the sim if it started it."""
        if self._loop is None or self._owner is None:
            return
        try:
            self._loop.run(self._owner.stop())
        finally:
            self._loop.close()
            self._loop = self._owner = None


RUN_SIM = _RunSim()


def _unavailable(reason: str) -> NoReturn:
    message = f"no naoqi-sim for the live tier: {reason}"
    if TARGET_REQUIRED:
        pytest.fail(message)
    pytest.skip(message + " (set NAOQI_E2E_TARGET=sim to make it a failure)")


def live_bridge_dict(streams: dict[str, Any] | None = None) -> dict[str, Any]:
    """The target's bridge config as JSON, for a server run in a subprocess: on sim,
    the run's sim (`spawn: "never"`), on real the robot at `NAOQI_E2E_IP`."""
    data: dict[str, Any]
    if TARGET == "sim":
        RUN_SIM.require()
        data = {
            "backend": "sim",
            "sim": {"spawn": "never", "config": {"naoqi": {"version": SIM_VERSION}}},
        }
    else:
        ip = require_env("NAOQI_E2E_IP")
        port = int(os.environ.get("NAOQI_E2E_PORT", "9559"))
        data = {"backend": "real", "robot": {"ip": ip, "port": port}}
    if streams is not None:
        data["streams"] = streams
    return data


def require_motion() -> None:
    """The motion level: on a robot, someone cleared the floor; a sim moves safely."""
    if TARGET == "real":
        require_flag("NAOQI_E2E_ALLOW_MOTION")


def require_interactive() -> None:
    """The interactive level: a person at the robot. A sim has no touch input yet."""
    if TARGET == "sim":
        pytest.skip("naoqi-sim has no touch input yet (specs/sim.md)")
    require_flag("NAOQI_E2E_INTERACTIVE")


# endregion


def require_env(name: str) -> str:
    """Return env var `name`, or skip the calling test if it's unset/empty."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set; skipping live test")
    return value


def require_flag(name: str) -> None:
    """Skip the calling test unless env var `name` is `1`, `true` or `yes`."""
    if not _flag(name):
        pytest.skip(f"{name} not set to 1; skipping live test")


def live_config(streams: StreamSettings | None = None) -> NaoqiBridgeConfig:
    """The target's bridge config with `streams`: the run's sim (`spawn: "never"`, so
    a test never starts a second one), or the robot at `NAOQI_E2E_IP` (skips when
    it's unset)."""
    if TARGET == "sim":
        RUN_SIM.require()
        return NaoqiBridgeConfig(
            backend="sim",
            streams=streams or StreamSettings(),
            sim=SimSettings.from_dict(
                {"spawn": "never", "config": {"naoqi": {"version": SIM_VERSION}}}
            ),
        )
    ip = require_env("NAOQI_E2E_IP")
    port = int(os.environ.get("NAOQI_E2E_PORT", "9559"))
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
        require_motion()
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
    assert isinstance(robot, NaoqiRobot)
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
