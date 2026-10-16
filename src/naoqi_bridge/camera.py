"""Camera feeds: ``CameraFeed`` / ``CameraFrame``, one reader per robot camera
(specs/camera.md).

``ALVideoDevice`` is pulled, not pushed: the feed holds the camera's one subscription
and a task that pulls it at the configured rate, publishing each new frame (a new
Naoqi timestamp) with the camera's pose, read in the same pull. A frame is a state
where only the latest matters, so the feed publishes through an ``Observable``: a
consumer slower than the camera sees fewer frames and never falls behind.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .errors import BridgeError, NotRunningError
from .observable import Observable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    import numpy as np
    import numpy.typing as npt

    from .config import CameraStream
    from .robot import Camera, CameraRead, NaoqiRobot

__all__ = ["CAMERA_DOWN_S", "CameraFeed", "CameraFrame"]

_logger = logging.getLogger(__name__)

# How long a camera may fail every read, or serve no new frame, before the feed warns
# (specs/camera.md "The feed"). Read at run time, so tests can shorten it.
CAMERA_DOWN_S = 5.0


@dataclass(frozen=True)
class CameraFrame:
    """One published frame (specs/camera.md "The frame")."""

    frame_id: int  # 1, 2, 3, … per feed — the key a result is matched on
    ts: float  # time.monotonic() when the bridge received the frame
    camera: Camera
    width: int
    height: int
    data: bytes = field(repr=False)  # BGR, 3 bytes per pixel, row-major
    naoqi_ts: float  # Naoqi's capture timestamp, seconds on the robot's clock
    # A row-major 4x4: camera -> FRAME_ROBOT, read with the frame.
    camera_transform: tuple[float, ...]
    fov: tuple[float, float]  # horizontal and vertical field of view, radians

    @property
    def image(self) -> npt.NDArray[np.uint8]:
        """``(height, width, 3)`` BGR, a read-only view of ``data`` (no copy)."""
        import numpy as np  # here: only a consumer of arrays pays for the import

        array = np.frombuffer(self.data, np.uint8).reshape(self.height, self.width, 3)
        array.flags.writeable = False
        return array


class CameraFeed:
    """One camera's reader (specs/camera.md "The feed").

    The bridge calls ``start()`` / ``stop()``; consumers read ``latest()`` from any
    thread or follow ``frames()``. ``frame_id`` counts on across sessions.
    """

    def __init__(self, camera: Camera, *, enabled: bool = False) -> None:
        self._camera: Camera = camera
        self._enabled = enabled
        self._frames: Observable[CameraFrame | None] = Observable(None)
        self._published = 0
        self._robot: NaoqiRobot | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def camera(self) -> Camera:
        return self._camera

    @property
    def enabled(self) -> bool:
        """Whether the bridge config enables this camera."""
        return self._enabled

    @property
    def running(self) -> bool:
        return self._robot is not None

    @property
    def published_count(self) -> int:
        """Frames published, ever, on this feed — the last ``frame_id``."""
        return self._published

    def latest(self) -> CameraFrame | None:
        """The newest frame; ``None`` before the session's first and outside one."""
        return self._frames.value

    # --- lifecycle (the bridge's) ---

    async def start(self, robot: NaoqiRobot, settings: CameraStream) -> None:
        """Subscribe the camera on ``robot`` and start pulling it. A no-op while
        running."""
        if self._robot is not None:
            return
        await asyncio.to_thread(
            robot.subscribe_camera, self._camera, settings.resolution, settings.fps
        )
        self._robot = robot
        self._task = asyncio.create_task(
            self._pull(robot, settings.fps), name=f"camera-{self._camera}"
        )

    async def stop(self) -> None:
        """Stop pulling, end every ``frames()``, reset ``latest()`` to ``None`` and
        unsubscribe the camera. A no-op on a feed that is not running."""
        robot, self._robot = self._robot, None
        if robot is None:
            return
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._frames.set(None)
        try:
            await asyncio.to_thread(robot.unsubscribe_camera, self._camera)
        except Exception:
            _logger.exception("%s camera: unsubscribing failed", self._camera)

    # --- consumers ---

    def frames(self) -> AsyncIterator[CameraFrame]:
        """Each frame published from the first ``async for`` on, latest-wins; ends
        when the session stops. ``BridgeError`` when the camera is disabled,
        ``NotRunningError`` outside a session, both raised here."""
        self._check()
        return self._follow()

    async def wait_for(self, predicate: Callable[[CameraFrame], bool]) -> CameraFrame:
        """The newest frame if it satisfies ``predicate``, else the first published
        one that does. ``NotRunningError`` if the session stops first."""
        self._check()
        latest = self._frames.value
        if latest is not None and predicate(latest):
            return latest
        async for frame in self._follow():
            if predicate(frame):
                return frame
        raise NotRunningError(f"the {self._camera} camera feed stopped")

    def _check(self) -> None:
        if not self._enabled:
            raise BridgeError(
                f"the {self._camera} camera is disabled "
                f"(streams.cameras.{self._camera}.enabled)"
            )
        if self._robot is None:
            raise NotRunningError("the bridge is not running; call start() first")

    async def _follow(self) -> AsyncIterator[CameraFrame]:
        if self._robot is None:  # stopped before the first ``async for``
            return
        async for frame in self._frames.changes():
            if frame is None:  # the session stopped
                return
            yield frame

    # --- the pull ---

    async def _pull(self, robot: NaoqiRobot, fps: int) -> None:
        """Pull the camera every ``1 / fps`` s, on the loop's clock from the start, and
        publish each frame with a new Naoqi timestamp."""
        loop = asyncio.get_running_loop()
        period = 1.0 / fps
        started = loop.time()
        tick = 0
        last_naoqi_ts: float | None = None
        failing_since: float | None = None
        warned_failing = False
        fresh_at = started  # when the last new frame came (or the pull started)
        warned_stale = False
        while True:
            try:
                read = await asyncio.to_thread(robot.read_camera, self._camera)
            except Exception:
                now = loop.time()
                _logger.debug("%s camera: read failed", self._camera, exc_info=True)
                if failing_since is None:
                    failing_since = now
                elif not warned_failing and now - failing_since >= CAMERA_DOWN_S:
                    warned_failing = True
                    _logger.warning(
                        "%s camera: every read has failed for %.0f s; keeping the "
                        "last frame and retrying",
                        self._camera,
                        now - failing_since,
                    )
            else:
                now = loop.time()
                if warned_failing:
                    _logger.info("%s camera: reads work again", self._camera)
                failing_since, warned_failing = None, False
                if read is not None and read.naoqi_ts != last_naoqi_ts:
                    last_naoqi_ts = read.naoqi_ts
                    fresh_at, warned_stale = now, False
                    self._publish(read)
                elif not warned_stale and now - fresh_at >= CAMERA_DOWN_S:
                    warned_stale = True
                    _logger.warning(
                        "%s camera: no new frame for %.0f s; Naoqi serves the camera "
                        "but nothing feeds it",
                        self._camera,
                        now - fresh_at,
                    )
            # The next tick on the grid: a slow read shortens the wait, never drifts it,
            # and ticks a read overran are skipped rather than run back to back.
            tick = max(tick + 1, math.floor((loop.time() - started) / period) + 1)
            await asyncio.sleep(max(0.0, started + tick * period - loop.time()))

    def _publish(self, read: CameraRead) -> None:
        self._published += 1
        self._frames.set(
            CameraFrame(
                frame_id=self._published,
                ts=time.monotonic(),
                camera=self._camera,
                width=read.width,
                height=read.height,
                data=read.data,
                naoqi_ts=read.naoqi_ts,
                camera_transform=read.transform,
                fov=read.fov,
            )
        )
