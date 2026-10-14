"""The live target: the environment that picks it, the session's sim, the probe, and
the helpers a live test opens its bridge with (specs/testing_support.md).

One target per run: a naoqi-sim the session starts and owns (`NAOQI_E2E_TARGET` unset
or `sim`), or the Nao at `NAOQI_E2E_IP` (`real`).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import os
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, NoReturn

import pytest

from ..bridge import NaoqiBridge
from ..config import (
    SIM_EXTRA,
    NaoqiBridgeConfig,
    RobotSettings,
    SimSettings,
    StreamSettings,
    sim_installed,
)
from ..robot import RobotConnectionError
from .capabilities import (
    PROFILE_VARIABLE,
    REQUIRED_VARIABLE,
    CapabilitySettings,
    Probe,
    check_names,
    flag_set,
    missing_reason,
    probe_capabilities,
    read_capability_settings,
)

if TYPE_CHECKING:
    from naoqi_sim import NaoqiSim

logger = logging.getLogger(__name__)

TARGETS = ("sim", "real")
SIM_VERSIONS = ("2.1", "2.8")
DEFAULT_PORT = 9559

# region The environment


@dataclass(frozen=True)
class LiveSettings:
    """The run's environment (specs/testing_support.md "The environment")."""

    target: Literal["sim", "real"]
    target_required: bool  # NAOQI_E2E_TARGET set: a target that can't run fails
    sim_version: str
    sim_viewer: bool
    ip: str | None
    port: int
    capabilities: CapabilitySettings


def read_settings(env: Mapping[str, str]) -> LiveSettings:
    """The settings in `env`; a `pytest.UsageError` naming the accepted words on an
    unknown target, version, profile or capability."""
    name = env.get("NAOQI_E2E_TARGET") or "sim"
    if name not in TARGETS:
        raise pytest.UsageError(
            f"NAOQI_E2E_TARGET={name!r}: choose from {', '.join(TARGETS)}"
        )
    target: Literal["sim", "real"] = "sim" if name == "sim" else "real"
    version = env.get("NAOQI_E2E_SIM_VERSION") or "2.1"
    if version not in SIM_VERSIONS:
        raise pytest.UsageError(
            f"NAOQI_E2E_SIM_VERSION={version!r}: choose from {', '.join(SIM_VERSIONS)}"
        )
    port_text = env.get("NAOQI_E2E_PORT") or str(DEFAULT_PORT)
    try:
        port = int(port_text)
    except ValueError:
        raise pytest.UsageError(
            f"NAOQI_E2E_PORT={port_text!r}: not a port number"
        ) from None
    return LiveSettings(
        target=target,
        target_required=bool(env.get("NAOQI_E2E_TARGET")),
        sim_version=version,
        sim_viewer=flag_set(env.get("NAOQI_E2E_SIM_VIEWER")),
        ip=env.get("NAOQI_E2E_IP") or None,
        port=port,
        capabilities=read_capability_settings(env, target),
    )


@cache
def live_settings() -> LiveSettings:
    """The process's settings, read from its environment once."""
    return read_settings(os.environ)


# endregion

# region The target


@dataclass(frozen=True)
class LiveTarget:
    """What the `live_target` fixture yields: the target and its capabilities."""

    kind: Literal["sim", "real"]
    naoqi_version: str | None
    probed: frozenset[str]
    declared: frozenset[str]
    sim: NaoqiSim | None = None  # the session's sim, for naoqi-sim's own API

    @property
    def caps(self) -> frozenset[str]:
        return self.probed | self.declared


# The target the running session opened, for `live_session`'s motion check.
_current: LiveTarget | None = None


def requires_caps(target: LiveTarget, *caps: str) -> None:
    """Skip the calling test unless `target` has every capability in `caps`: the
    `requires` marker's check, for a need only known at run time."""
    check_names(caps, "requires_caps")
    reason = missing_reason(target.caps, caps)
    if reason is not None:
        pytest.skip(reason)


def check_expected(target: LiveTarget, settings: CapabilitySettings) -> None:
    """Fail when `target` lacks a capability the run expects: its profile's, or one
    `NAOQI_E2E_REQUIRED_CAPS` names (specs/testing_support.md "Profiles")."""
    missing = sorted(settings.expected - target.caps)
    if not missing:
        return
    asked = [f"profile {settings.profile}"]
    if settings.required:
        asked.append(f"{REQUIRED_VARIABLE}={','.join(sorted(settings.required))}")
    pytest.fail(
        f"the target lacks {', '.join(missing)}, which the run expects "
        f"({'; '.join(asked)}); it has {', '.join(sorted(target.caps)) or 'nothing'}. "
        f"Pick the profile that fits it with {PROFILE_VARIABLE}",
        pytrace=False,
    )


def sim_config(settings: LiveSettings) -> dict[str, Any]:
    """The session's sim, as a naoqi-sim config file holds it: headless with the render
    camera, the placeholder model, a silent loudspeaker and the fake microphone; or
    the window, with `NAOQI_E2E_SIM_VIEWER=1`."""
    viewer: dict[str, Any] = (
        {"headless": False}
        if settings.sim_viewer
        else {"headless": True, "variant": "placeholder"}
    )
    return {
        "naoqi": {"version": settings.sim_version},
        "viewer": viewer,
        "video_input": {"source": "render"},
        "audio_output": {"mode": "silent"},
        "audio_input": {"source": "fake"},
    }


def _unavailable(settings: LiveSettings, reason: str) -> NoReturn:
    message = f"no {settings.target} target for the live tier: {reason}"
    if settings.target_required:
        pytest.fail(message, pytrace=False)
    pytest.skip(
        message + f" (set NAOQI_E2E_TARGET={settings.target} to make it a failure)"
    )


class _LoopThread:
    """An event loop running in its own thread, for the session's sim: its start and
    its stop run on the same loop, which every test's `asyncio.run` would not be."""

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


@contextlib.contextmanager
def _session_sim(settings: LiveSettings) -> Iterator[NaoqiSim | None]:
    """On `sim`, the session's sim, started with `spawn: "always"` so the run owns it
    and holds its `NaoqiSim`, and stopped at the end; on `real`, `None`."""
    if settings.target != "sim":
        if settings.ip is None:
            _unavailable(settings, "set NAOQI_E2E_IP to the robot's address")
        yield None
        return
    if not sim_installed():
        _unavailable(settings, f"install {SIM_EXTRA}")
    from naoqi_sim import NaoqiSimConfig

    from ..sim import acquire_sim

    sim_settings = SimSettings(
        spawn="always", config=NaoqiSimConfig.from_dict(sim_config(settings))
    )
    loop = _LoopThread()
    try:
        lease = loop.run(acquire_sim(sim_settings))
    except RobotConnectionError as e:
        loop.close()
        _unavailable(settings, str(e))
    logger.warning(
        "Live tier on a naoqi-sim, NAOqi %s (%s)",
        settings.sim_version,
        "the window" if settings.sim_viewer else "headless",
    )
    try:
        yield lease.sim
    finally:
        try:
            loop.run(lease.release())
        finally:
            loop.close()


def _target_url(settings: LiveSettings) -> str:
    if settings.target == "sim":
        from ..sim import SIM_URL

        return SIM_URL
    return f"tcp://{settings.ip}:{settings.port}"


def _probe(settings: LiveSettings, sim: NaoqiSim | None) -> Probe:
    """Probe the target: a bridge with no streams (which also checks the target
    answers) for the catalog, and the harness's own qi session for the rest."""
    import qi

    async def run() -> Probe:
        async with NaoqiBridge(live_config(settings=settings)) as bridge:
            session = qi.Session()
            session.connect(_target_url(settings))
            try:
                return probe_capabilities(
                    session, bridge, owns_fake_audio=sim is not None
                )
            finally:
                session.close()

    try:
        return asyncio.run(run())
    except RobotConnectionError as e:
        _unavailable(settings, str(e))


@contextlib.contextmanager
def open_target(settings: LiveSettings) -> Iterator[LiveTarget]:
    """Bring the target up, probe it, check what the run expects of it, and yield it;
    release what was started at the end. A target that can't run skips the session,
    or fails it when NAOQI_E2E_TARGET names it."""
    global _current
    if importlib.util.find_spec("qi") is None:
        _unavailable(settings, "no qi wheel on this platform")
    with _session_sim(settings) as sim:
        probe = _probe(settings, sim)
        target = LiveTarget(
            kind=settings.target,
            naoqi_version=probe.naoqi_version,
            probed=probe.caps,
            declared=settings.capabilities.declared,
            sim=sim,
        )
        _current = target
        try:
            check_expected(target, settings.capabilities)
            yield target
        finally:
            _current = None


# endregion

# region Helpers


def live_bridge_dict(
    streams: dict[str, Any] | None = None, *, settings: LiveSettings | None = None
) -> dict[str, Any]:
    """The target's bridge config as JSON, for a server run in a subprocess: on sim,
    the session's sim (`spawn: "never"`), on real the robot at `NAOQI_E2E_IP`."""
    settings = settings or live_settings()
    data: dict[str, Any]
    if settings.target == "sim":
        data = {
            "backend": "sim",
            "sim": {
                "spawn": "never",
                "config": {"naoqi": {"version": settings.sim_version}},
            },
        }
    else:
        if settings.ip is None:
            _unavailable(settings, "set NAOQI_E2E_IP to the robot's address")
        data = {"backend": "real", "robot": {"ip": settings.ip, "port": settings.port}}
    if streams is not None:
        data["streams"] = streams
    return data


def live_config(
    streams: StreamSettings | None = None, *, settings: LiveSettings | None = None
) -> NaoqiBridgeConfig:
    """The target's bridge config with `streams`: the session's sim borrowed
    (`spawn: "never"`, so a test never starts a second one), or the robot."""
    settings = settings or live_settings()
    streams = streams or StreamSettings()
    if settings.target == "sim":
        return NaoqiBridgeConfig(
            backend="sim",
            streams=streams,
            sim=SimSettings.from_dict(
                {
                    "spawn": "never",
                    "config": {"naoqi": {"version": settings.sim_version}},
                }
            ),
        )
    if settings.ip is None:
        _unavailable(settings, "set NAOQI_E2E_IP to the robot's address")
    return NaoqiBridgeConfig(
        backend="real",
        robot=RobotSettings(ip=settings.ip, port=settings.port),
        streams=streams,
    )


@contextlib.asynccontextmanager
async def live_session(
    config: NaoqiBridgeConfig, *, motion: bool = False
) -> AsyncIterator[NaoqiBridge]:
    """A running bridge on the target, left as it was found: eyes white and, with
    `motion` (motors woken on entry), at rest. `motion` needs `room_to_move`: a test
    that moves the robot is marked `@pytest.mark.requires("room_to_move")`."""
    if motion and (_current is None or "room_to_move" not in _current.caps):
        pytest.fail(
            "live_session(motion=True) moves the robot, and the target lacks "
            "room_to_move: mark the test @pytest.mark.requires('room_to_move')",
            pytrace=False,
        )
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


# endregion
