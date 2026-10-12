"""Mic feed: ``MicFeed`` / ``MicChunk``, the one owner of the robot's microphone
(specs/microphone.md).

Naoqi pushes every capture buffer to the one service subscribed to ``ALAudioDevice``,
on a Naoqi thread. The feed is that subscription: each push is stamped with a sequence
number and its arrival time and published into a ring of the last ``MIC_RING_CHUNKS``
chunks. Every ``audio_input()`` is a subscriber of its own over the ring, holding a
cursor on the chunk it yields next: each receives every chunk, in order, at its own
pace, and a subscriber lapped by the ring loses only its own chunks, with a warning.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import BridgeError
from .robot import AUDIO_SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .config import AudioChannel
    from .robot import NaoRobot

__all__ = ["MIC_RING_CHUNKS", "MicChunk", "MicFeed"]

_logger = logging.getLogger(__name__)

# The ring's length in chunks (specs/microphone.md "The feed"). Read at start(), so
# tests can shorten it.
MIC_RING_CHUNKS = 200

# A waiting subscriber: its event, set from Naoqi's thread through its loop.
type _Waiter = tuple[asyncio.AbstractEventLoop, asyncio.Event]


@dataclass(frozen=True)
class MicChunk:
    """One published capture buffer (specs/microphone.md "The chunk")."""

    seq: int  # 0, 1, 2, … per feed — the subscribers' cursor counts these
    ts: float  # time.monotonic() when the bridge received the buffer
    data: bytes  # int16 LE PCM, interleaved — the buffer Naoqi pushed
    channels: int
    samples_per_channel: int


class MicFeed:
    """The one owner of the robot's microphone (specs/microphone.md "The feed").

    ``start()`` subscribes to the robot's audio, ``subscribe()`` makes an
    ``audio_input()`` stream over the ring, ``latest()`` is the newest chunk from any
    thread, ``stop()`` unsubscribes and ends every subscriber. ``seq`` counts on
    across sessions.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capacity = MIC_RING_CHUNKS
        self._ring: list[MicChunk | None] = []
        self._head = 0  # the next seq — counts on across sessions
        self._session = 0  # bumped at each start(): a subscriber ends with its session
        self._session_start = 0  # the first seq of the running session
        self._running = False
        self._waiters: set[_Waiter] = set()
        self._robot: NaoRobot | None = None
        self._channels = 1

    @property
    def running(self) -> bool:
        return self._running

    @property
    def sample_rate(self) -> int:
        return AUDIO_SAMPLE_RATE

    @property
    def channels(self) -> int:
        """1 with every single-microphone mode the config offers."""
        return self._channels

    @property
    def published_count(self) -> int:
        """Chunks published, ever, on this feed — the next chunk's ``seq``."""
        with self._lock:
            return self._head

    def latest(self) -> MicChunk | None:
        """The newest chunk, or ``None`` before the session's first and after ``stop()``."""
        with self._lock:
            if not self._running or self._head == self._session_start:
                return None
            return self._ring[(self._head - 1) % self._capacity]

    async def start(self, robot: NaoRobot, channel: AudioChannel) -> None:
        """Subscribe to ``robot``'s ``channel`` microphone. A no-op while running."""
        if self._running:
            return
        with self._lock:
            self._capacity = MIC_RING_CHUNKS
            self._ring = [None] * self._capacity
            self._session += 1
            self._session_start = self._head
            self._running = True
        try:
            await asyncio.to_thread(robot.subscribe_audio, self._publish, channel)
        except BaseException:
            await self._end_session()
            raise
        self._robot = robot

    async def stop(self) -> None:
        """Unsubscribe, end every subscriber and reset ``latest()`` to ``None``.
        A no-op on a feed that is not running."""
        if not self._running:
            return
        robot, self._robot = self._robot, None
        await self._end_session()
        if robot is not None:
            try:
                await asyncio.to_thread(robot.unsubscribe_audio)
            except Exception:
                _logger.exception(
                    "mic feed: unsubscribing from the robot's audio failed"
                )

    async def _end_session(self) -> None:
        with self._lock:
            self._running = False
            self._ring = [None] * self._capacity
            waiters = tuple(self._waiters)
        _wake(waiters)

    # --- subscribers ---

    def subscribe(self, *, preroll_s: float = 0.0) -> AsyncIterator[bytes]:
        """A new subscriber over the ring (specs/microphone.md "Subscribers"): int16 LE
        ``bytes`` per chunk, from the call on — or from up to ``preroll_s`` seconds
        before it, as far as the ring reaches. ``ValueError`` on a negative
        ``preroll_s``; ``BridgeError`` when the feed is not running. The stream ends
        when the feed stops."""
        if preroll_s < 0:
            raise ValueError(f"preroll_s must be >= 0, got {preroll_s}")
        with self._lock:
            if not self._running:
                raise BridgeError("the mic feed is not running")
            cursor = self._head
            if preroll_s > 0:
                cutoff = time.monotonic() - preroll_s
                oldest = max(self._head - self._capacity, self._session_start)
                while cursor > oldest:
                    previous = self._ring[(cursor - 1) % self._capacity]
                    if previous is None or previous.ts < cutoff:
                        break
                    cursor -= 1
            session = self._session
        return self._iterate(cursor, session)

    async def _iterate(self, cursor: int, session: int) -> AsyncIterator[bytes]:
        event = asyncio.Event()
        waiter: _Waiter = (asyncio.get_running_loop(), event)
        with self._lock:
            self._waiters.add(waiter)
        try:
            while True:
                # Cleared before head is read: a chunk published after the read sets
                # it again, so the wait below never misses one.
                event.clear()
                lost = 0
                with self._lock:
                    if not self._running or self._session != session:
                        return
                    head = self._head
                    oldest = max(head - self._capacity, self._session_start)
                    if cursor < oldest:  # lapped: those chunks were overwritten
                        lost, cursor = oldest - cursor, oldest
                    chunk = (
                        self._ring[cursor % self._capacity] if cursor < head else None
                    )
                if lost:
                    self._report_gap(lost, chunk)
                if chunk is None:
                    await event.wait()
                    continue
                cursor += 1
                yield chunk.data
        finally:
            with self._lock:
                self._waiters.discard(waiter)

    def _report_gap(self, lost: int, chunk: MicChunk | None) -> None:
        samples = 0 if chunk is None else chunk.samples_per_channel
        ms = 1000.0 * lost * samples / AUDIO_SAMPLE_RATE
        _logger.warning(
            "audio_input: a subscriber fell %d chunks (%.0f ms) behind the mic; "
            "resuming from the oldest buffered chunk",
            lost,
            ms,
        )

    # --- the push ---

    def _publish(self, channels: int, samples_per_channel: int, buffer: bytes) -> None:
        """Naoqi's audio callback, on Naoqi's thread: the push is the publish."""
        with self._lock:
            if not self._running:
                return
            self._channels = channels
            chunk = MicChunk(
                self._head,
                time.monotonic(),
                bytes(buffer),
                channels,
                samples_per_channel,
            )
            self._ring[self._head % self._capacity] = chunk
            self._head += 1
            waiters = tuple(self._waiters)
        _wake(waiters)


def _wake(waiters: tuple[_Waiter, ...]) -> None:
    for loop, event in waiters:
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:  # the subscriber's loop is closed: nothing left to wake
            pass
