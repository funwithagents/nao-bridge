"""The mic feed (specs/microphone.md) over a FakeNaoRobot whose paced push is paused,
so each test pushes numbered chunks itself: every subscriber gets every chunk in order,
a lapped one reports the gap, pre-roll reaches back, cancellation and session end.

Async runs via ``asyncio.run``.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from nao_bridge import microphone
from nao_bridge.errors import BridgeError
from nao_bridge.fake_robot import FakeNaoRobot
from nao_bridge.microphone import MicFeed


def quiet_robot() -> FakeNaoRobot:
    robot = FakeNaoRobot()
    robot.audio_chunk_s = None  # only the chunks a test pushes
    return robot


def push(robot: FakeNaoRobot, index: int) -> None:
    """Push one mono chunk whose single sample is ``index``."""
    robot.emit_audio(1, 1, index.to_bytes(2, "little"))


def index_of(chunk: bytes) -> int:
    return int.from_bytes(chunk, "little")


async def take(stream: AsyncIterator[bytes], n: int) -> list[int]:
    out: list[int] = []
    async with asyncio.timeout(2.0):
        async for chunk in stream:
            out.append(index_of(chunk))
            if len(out) == n:
                break
    return out


async def push_paced(robot: FakeNaoRobot, indexes: range) -> None:
    for i in indexes:
        push(robot, i)
        await asyncio.sleep(0.001)


def test_two_subscribers_each_receive_every_chunk_in_order():
    async def run() -> tuple[list[int], list[int]]:
        robot, feed = quiet_robot(), MicFeed()
        await feed.start(robot, "front")
        first = asyncio.create_task(take(feed.subscribe(), 30))
        second = asyncio.create_task(take(feed.subscribe(), 30))
        await asyncio.sleep(0)
        await push_paced(robot, range(30))
        result = await first, await second
        await feed.stop()
        return result

    first, second = asyncio.run(run())
    assert first == second == list(range(30))


def test_a_lapped_subscriber_reports_the_gap_and_resumes_while_a_fast_one_loses_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(microphone, "MIC_RING_CHUNKS", 8)

    async def run() -> tuple[list[int], list[int]]:
        robot, feed = quiet_robot(), MicFeed()
        await feed.start(robot, "front")
        slow = feed.subscribe()  # cursor at 0, not driven yet
        fast = asyncio.create_task(take(feed.subscribe(), 20))
        await asyncio.sleep(0)
        await push_paced(robot, range(20))
        fast_got = await fast
        slow_task = asyncio.create_task(take(slow, 10))
        await asyncio.sleep(0)
        await push_paced(robot, range(20, 22))
        slow_got = await slow_task
        await feed.stop()
        return fast_got, slow_got

    fast_got, slow_got = asyncio.run(run())
    assert fast_got == list(range(20))
    assert slow_got == list(range(12, 22))  # the ring's 8 oldest, then the new ones
    gaps = [r for r in caplog.records if "behind the mic" in r.getMessage()]
    assert len(gaps) == 1
    assert "12 chunks" in gaps[0].getMessage()


def test_preroll_reaches_back_into_the_ring():
    async def run() -> tuple[list[int], list[int]]:
        robot, feed = quiet_robot(), MicFeed()
        await feed.start(robot, "front")
        await push_paced(robot, range(5))
        with_preroll = asyncio.create_task(take(feed.subscribe(preroll_s=10.0), 7))
        without = asyncio.create_task(take(feed.subscribe(), 2))
        await asyncio.sleep(0)
        await push_paced(robot, range(5, 7))
        result = await with_preroll, await without
        await feed.stop()
        return result

    with_preroll, without = asyncio.run(run())
    assert with_preroll == list(range(7))
    assert without == [5, 6]


def test_a_negative_preroll_and_a_stopped_feed_raise_at_the_call():
    feed = MicFeed()
    with pytest.raises(BridgeError):
        feed.subscribe()

    async def run() -> None:
        await feed.start(quiet_robot(), "front")
        with pytest.raises(ValueError):
            feed.subscribe(preroll_s=-1)
        await feed.stop()

    asyncio.run(run())


def test_cancelling_one_subscriber_leaves_the_others_streaming():
    async def run() -> list[int]:
        robot, feed = quiet_robot(), MicFeed()
        await feed.start(robot, "front")
        doomed = asyncio.create_task(take(feed.subscribe(), 100))
        survivor = asyncio.create_task(take(feed.subscribe(), 10))
        await asyncio.sleep(0)
        await push_paced(robot, range(5))
        doomed.cancel()
        await asyncio.gather(doomed, return_exceptions=True)
        await push_paced(robot, range(5, 10))
        result = await survivor
        await feed.stop()
        return result

    assert asyncio.run(run()) == list(range(10))


def test_stopping_ends_subscribers_and_sessions_do_not_leak():
    async def run() -> tuple[list[int], bool, list[int], int]:
        robot, feed = quiet_robot(), MicFeed()
        latest_before = feed.latest()
        await feed.start(robot, "front")
        session_one = feed.subscribe()
        await push_paced(robot, range(3))
        assert feed.latest() is not None
        await feed.stop()
        ended: list[int] = []
        async with asyncio.timeout(1.0):
            async for chunk in session_one:  # ends at once: its session is over
                ended.append(index_of(chunk))
        stopped_latest_is_none = feed.latest() is None and latest_before is None

        await feed.start(robot, "front")
        session_two = asyncio.create_task(take(feed.subscribe(preroll_s=10.0), 2))
        await asyncio.sleep(0)
        await push_paced(robot, range(100, 102))
        second = await session_two
        count = feed.published_count
        await feed.stop()
        return ended, stopped_latest_is_none, second, count

    ended, stopped_latest_is_none, second, count = asyncio.run(run())
    assert ended == []
    assert stopped_latest_is_none
    assert second == [100, 101]  # pre-roll never reaches the previous session
    assert count == 5  # seq counts on across sessions


def test_the_feed_subscribes_to_the_configured_microphone_and_unsubscribes():
    async def run() -> list[tuple[str, dict[str, object]]]:
        robot, feed = quiet_robot(), MicFeed()
        await feed.start(robot, "rear")
        await feed.stop()
        return robot.commands

    assert asyncio.run(run()) == [
        ("subscribe_audio", {"channel": "rear"}),
        ("unsubscribe_audio", {}),
    ]
