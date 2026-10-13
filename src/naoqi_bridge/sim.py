"""The ``sim`` backend's lease on a naoqi-sim (specs/sim.md).

``acquire_sim`` starts a naoqi-sim and owns it, or borrows the one already running on
this machine, as ``sim.spawn`` says; ``SimLease.release`` stops an owned sim and leaves
a borrowed one running. The bridge then connects its ordinary ``NaoqiRobot`` to
``SIM_HOST:SIM_PORT``. This is the one module that starts naoqi-sim, imported inside
the functions, so ``naoqi_bridge`` imports without the ``[sim]`` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import time
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any

from .config import SIM_EXTRA, SimSettings
from .robot import RobotConnectionError

if TYPE_CHECKING:
    from naoqi_sim import NaoqiSim, NaoqiSimConfig, StackStatus

__all__ = ["SIM_HOST", "SIM_PORT", "SimLease", "acquire_sim", "naoqi_sim_config"]

logger = logging.getLogger(__name__)

# naoqi-sim's fixed address: one sim per machine.
SIM_HOST = "127.0.0.1"
SIM_PORT = 9559
SIM_URL = f"tcp://{SIM_HOST}:{SIM_PORT}"

# How often a sim that is still booting is looked at again.
BOOT_POLL_S = 1.0


@dataclass
class SimLease:
    """A naoqi-sim the bridge may use: ``owned`` when this lease started it."""

    url: str
    owned: bool
    # What the sim's NaoqiSim service reports, e.g. "2.1.4.13".
    naoqi_version: str
    _sim: NaoqiSim | None = field(default=None, repr=False)

    async def release(self) -> None:
        """Stop an owned sim (its containers go down, in seconds); a no-op on a
        borrowed one, and on a lease already released."""
        sim, self._sim = self._sim, None
        if sim is not None:
            await sim.stop()


def _naoqi_sim() -> ModuleType:
    try:
        return importlib.import_module("naoqi_sim")
    except ImportError as e:  # the config refuses it first; a direct caller may not
        raise RobotConnectionError(
            f"the sim backend needs naoqi-sim: install {SIM_EXTRA}"
        ) from e


def naoqi_sim_config(settings: SimSettings) -> NaoqiSimConfig:
    """The naoqi-sim config the ``sim`` block asks for: its own, or naoqi-sim's
    defaults."""
    return settings.config or _naoqi_sim().NaoqiSimConfig()


def _runs(status: StackStatus) -> bool:
    """Whether a naoqi-sim runs (ready, or still booting): one of its containers is
    up. Containers a dead run left behind (exited) don't count: starting replaces
    them."""
    return status.ready or any(c.state == "running" for c in status.containers)


async def acquire_sim(settings: SimSettings) -> SimLease:
    """Start a naoqi-sim or borrow the one running, as ``settings.spawn`` says
    (specs/sim.md, "Own it or borrow it"). Raises ``RobotConnectionError`` when there
    is no sim to use, chained to naoqi-sim's error when naoqi-sim said why.
    Cancel-safe: a sim being started is stopped before the cancel propagates."""
    naoqi_sim = _naoqi_sim()
    config = naoqi_sim_config(settings)
    version = config.naoqi.version
    try:
        status = await naoqi_sim.read_status()
        if _runs(status):
            if settings.spawn == "always":
                raise RobotConnectionError(
                    "a naoqi-sim already runs on this machine, and sim.spawn 'always' "
                    "asks for one of its own: stop it, or set sim.spawn to 'auto'"
                )
            status = await _wait_ready(naoqi_sim, status, config.naoqi.ready_timeout_s)
            return SimLease(
                SIM_URL, owned=False, naoqi_version=_checked(status, version)
            )
        if settings.spawn == "never":
            raise RobotConnectionError(
                "no naoqi-sim runs on this machine, and sim.spawn 'never' doesn't start "
                "one: start it with `naoqi-sim run`, or set sim.spawn to 'auto'"
            )
        return await _start(naoqi_sim, config)
    except naoqi_sim.NaoqiSimError as e:
        raise RobotConnectionError(f"naoqi-sim: {e}") from e


async def _start(naoqi_sim: ModuleType, config: Any) -> SimLease:
    sim: NaoqiSim = naoqi_sim.NaoqiSim(config)
    await sim.start()  # cancel-safe: stops what it started before re-raising
    try:
        status = await sim.status()
    except BaseException:
        with contextlib.suppress(Exception):
            await asyncio.shield(sim.stop())
        raise
    logger.info("Started naoqi-sim on NAOqi %s", status.naoqi_version)
    return SimLease(sim.url, owned=True, naoqi_version=status.naoqi_version, _sim=sim)


async def _wait_ready(
    naoqi_sim: ModuleType, status: StackStatus, timeout_s: float
) -> StackStatus:
    """Wait for a sim that is still booting, up to ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while not status.ready:
        if time.monotonic() >= deadline:
            raise RobotConnectionError(
                f"the naoqi-sim running on this machine was not ready within {timeout_s:g} s"
            )
        logger.info("Waiting for the naoqi-sim running on this machine to be ready")
        await asyncio.sleep(BOOT_POLL_S)
        status = await naoqi_sim.read_status()
        if not _runs(status):
            raise RobotConnectionError(
                "the naoqi-sim that was booting on this machine stopped"
            )
    return status


def _checked(status: StackStatus, version: str) -> str:
    """The borrowed sim's NAOqi version, which must be the one asked for."""
    assert status.naoqi is not None  # ready
    running = status.naoqi.naoqi_version
    if not running.startswith(f"{version}."):
        raise RobotConnectionError(
            f"the naoqi-sim running on this machine is NAOqi {running}, "
            f"not {version} as sim.config.naoqi.version asks"
        )
    return running
