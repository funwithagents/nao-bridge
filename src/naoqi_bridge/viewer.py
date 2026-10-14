"""The bridge's viewer: a naoqi-viewer window mirroring the robot (specs/viewer.md).

``viewer_target`` decides whether the viewer opens and on which Naoqi; ``open_viewer``
launches naoqi-viewer in mirror mode on it and ``close_viewer`` closes it. This is the
one module that launches naoqi-viewer, imported inside the functions, so
``naoqi_bridge`` imports without the ``[viewer]`` extra.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import logging
from types import ModuleType
from typing import TYPE_CHECKING

from .config import VIEWER_EXTRA, NaoqiBridgeConfig, ViewerSettings
from .errors import ViewerError
from .sim import SimLease, naoqi_sim_config

if TYPE_CHECKING:
    from naoqi_viewer import NaoqiViewer

__all__ = ["close_viewer", "open_viewer", "viewer_target"]

logger = logging.getLogger(__name__)


def viewer_target(config: NaoqiBridgeConfig, lease: SimLease | None) -> str | None:
    """The Naoqi URL the viewer mirrors, or ``None`` when it doesn't open: disabled,
    or skipped with a warning saying why (specs/viewer.md, "Which robot it mirrors").
    ``lease`` is the sim the bridge acquired, on the ``sim`` backend."""
    if not config.viewer.enabled:
        return None
    if config.backend == "fake":
        logger.warning(
            "viewer.enabled is ignored on the fake backend: the viewer mirrors a Naoqi "
            "over qi, and the fake has none"
        )
        return None
    if config.backend == "sim":
        assert lease is not None
        if lease.owned and not naoqi_sim_config(config.sim).viewer.headless:
            logger.warning(
                "viewer not opened: the sim this bridge started shows its own window; "
                "set sim.config.viewer.headless to true to use the bridge's viewer "
                "instead"
            )
            return None
        return lease.url
    return f"tcp://{config.robot.ip}:{config.robot.port}"


def _naoqi_viewer() -> ModuleType:
    try:
        return importlib.import_module("naoqi_viewer")
    except ImportError as e:  # the config refuses it first; a direct caller may not
        raise ViewerError(
            f"the viewer needs naoqi-viewer: install {VIEWER_EXTRA}"
        ) from e


async def open_viewer(settings: ViewerSettings, url: str) -> NaoqiViewer:
    """Launch naoqi-viewer in mirror mode on ``url``, returning once its window is up.
    Raises ``ViewerError`` when it can't launch. A cancel waits for the launch in
    flight (bounded by its ``launch_timeout_s``), closes the viewer, then propagates."""
    naoqi_viewer = _naoqi_viewer()
    base = settings.config or naoqi_viewer.NaoqiViewerConfig()
    config = dataclasses.replace(
        base,
        mode="mirror",
        headless=False,
        naoqi=dataclasses.replace(base.naoqi, url=url),
    )
    viewer: NaoqiViewer = naoqi_viewer.NaoqiViewer(config)
    launch = asyncio.ensure_future(asyncio.to_thread(viewer.launch))
    try:
        await asyncio.shield(launch)
    except asyncio.CancelledError:
        await asyncio.wait({launch})
        if not launch.cancelled():
            launch.exception()  # retrieved: the cancel is what propagates
        await close_viewer(viewer)
        raise
    except naoqi_viewer.LaunchError as e:
        raise ViewerError(f"the viewer could not open: {e}") from e
    logger.info("Viewer open, mirroring %s", url)
    return viewer


async def close_viewer(viewer: NaoqiViewer) -> None:
    """Close the viewer's window; harmless if it's already gone."""
    try:
        await asyncio.to_thread(viewer.close)
    except Exception:
        logger.exception("Closing the viewer failed")
