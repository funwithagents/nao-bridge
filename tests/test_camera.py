"""Camera feeds (specs/camera.md) on the ``fake`` backend, driven through
``bridge.cameras`` the way a caller uses them: publishing, latest-wins subscribers,
the session's lifecycle, the checks at the call, failures and the frame itself.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
import itertools
import logging
import subprocess
import sys
from collections.abc import Callable

import numpy as np
import pytest

from naoqi_bridge import (
    BridgeError,
    CameraFrame,
    CameraStream,
    CameraStreams,
    NaoqiBridge,
    NaoqiBridgeConfig,
    NotRunningError,
    StreamSettings,
)
from naoqi_bridge import camera as camera_module
from naoqi_bridge.fake_robot import (
    FAKE_CAMERA_FOV,
    FAKE_CAMERA_TRANSFORMS,
    FakeNaoqiRobot,
)
from naoqi_bridge.robot import CameraRead

TOP_ONLY = NaoqiBridgeConfig(
    streams=StreamSettings(
        cameras=CameraStreams(
            top=CameraStream(enabled=True, resolution="qqvga", fps=30)
        )
    )
)


def fake(bridge: NaoqiBridge) -> FakeNaoqiRobot:
    robot = bridge.robot
    assert isinstance(robot, FakeNaoqiRobot)
    return robot


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def collect(bridge: NaoqiBridge, count: int) -> list[CameraFrame]:
    frames: list[CameraFrame] = []
    async with asyncio.timeout(2.0):
        async for frame in bridge.cameras["top"].frames():
            frames.append(frame)
            if len(frames) == count:
                break
    return frames


def test_a_feed_publishes_each_new_frame_once_in_order():
    async def run() -> tuple[list[CameraFrame], int, int, int]:
        async with NaoqiBridge(TOP_ONLY) as bridge:
            feed = bridge.cameras["top"]
            await feed.wait_for(lambda _: True)
            frames = await collect(bridge, 4)
            # The fake repeats its frame from now on: nothing more is published.
            fake(bridge).camera_period_s = None
            await asyncio.sleep(0.05)
            frozen_at = feed.published_count
            await asyncio.sleep(0.15)  # several pulls at 30 fps
            latest = feed.latest()
            assert latest is not None
            return frames, frozen_at, feed.published_count, latest.frame_id

    frames, frozen_at, count_after, latest_id = asyncio.run(run())
    ids = [f.frame_id for f in frames]
    assert ids == list(range(ids[0], ids[0] + 4))  # a subscriber that keeps up
    assert ids[0] >= 2  # the first frame was published before frames() was followed
    stamps = [f.naoqi_ts for f in frames]
    assert stamps == sorted(set(stamps))  # each Naoqi frame once, in order
    assert count_after == frozen_at == latest_id  # published_count is the last id


def test_latest_is_none_outside_a_session_and_frame_ids_count_on_across_restarts():
    async def run() -> tuple[object, int, object, int]:
        bridge = NaoqiBridge(TOP_ONLY)
        feed = bridge.cameras["top"]
        before = feed.latest()
        async with bridge:
            first_session = (await feed.wait_for(lambda _: True)).frame_id
        after = feed.latest()
        async with bridge:
            last = feed.published_count
            second_session = (await feed.wait_for(lambda f: f.frame_id > last)).frame_id
        return before, first_session, after, second_session

    before, first_session, after, second_session = asyncio.run(run())
    assert before is None and after is None
    assert first_session == 1
    assert second_session > first_session


def test_two_subscribers_each_see_the_frames_and_a_slow_one_gets_the_newest():
    async def run() -> tuple[list[int], list[int], int]:
        async with NaoqiBridge(TOP_ONLY) as bridge:
            feed = bridge.cameras["top"]
            fast: list[int] = []
            slow: list[int] = []

            async def follow(into: list[int], pause: float) -> None:
                async for frame in feed.frames():
                    into.append(frame.frame_id)
                    await asyncio.sleep(pause)

            tasks = [
                asyncio.create_task(follow(fast, 0.0)),
                asyncio.create_task(follow(slow, 0.2)),
            ]
            await wait_until(lambda: len(slow) >= 3)
            published = feed.published_count
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return fast, slow, published

    fast, slow, published = asyncio.run(run())
    assert fast == list(range(fast[0], fast[0] + len(fast)))  # none missed
    # 0.2 s per frame at 30 fps: the slow one skips to the newest each time.
    assert all(b - a > 1 for a, b in itertools.pairwise(slow))
    assert slow[-1] >= published - 1


def test_frames_end_with_the_session_and_a_cancelled_one_leaves_the_others():
    async def run() -> bool:
        bridge = NaoqiBridge(TOP_ONLY)
        await bridge.start()
        feed = bridge.cameras["top"]
        counts = {"cancelled": 0, "survivor": 0}

        async def follow(name: str) -> None:
            async for _ in feed.frames():
                counts[name] += 1

        cancelled = asyncio.create_task(follow("cancelled"))
        survivor = asyncio.create_task(follow("survivor"))
        await wait_until(lambda: counts["cancelled"] >= 2)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        seen = counts["survivor"]
        await wait_until(lambda: counts["survivor"] >= seen + 2)  # it goes on
        await bridge.stop()
        async with asyncio.timeout(1.0):
            await survivor  # ended by the stop, not cancelled
        return not survivor.cancelled()

    assert asyncio.run(run())


def test_frames_checks_are_made_at_the_call():
    async def run() -> None:
        bridge = NaoqiBridge(TOP_ONLY)
        with pytest.raises(NotRunningError):
            bridge.cameras["top"].frames()
        async with bridge:
            bottom = bridge.cameras["bottom"]
            with pytest.raises(BridgeError, match="bottom camera is disabled"):
                bottom.frames()
            with pytest.raises(BridgeError, match="disabled"):
                await bottom.wait_for(lambda _: True)
            assert bottom.latest() is None
        with pytest.raises(NotRunningError):
            await bridge.cameras["top"].wait_for(lambda _: True)

    asyncio.run(run())


def test_both_feeds_exist_from_construction_and_the_mapping_is_read_only():
    bridge = NaoqiBridge()
    assert set(bridge.cameras) == {"top", "bottom"}
    assert bridge.cameras["bottom"].camera == "bottom"
    with pytest.raises(TypeError):
        bridge.cameras["top"] = bridge.cameras["bottom"]  # type: ignore[index]


def test_the_bridge_subscribes_exactly_the_enabled_cameras_and_gives_them_back():
    config = NaoqiBridgeConfig(
        streams=StreamSettings(
            cameras=CameraStreams(
                bottom=CameraStream(enabled=True, resolution="vga", fps=5)
            )
        )
    )

    async def run() -> list[tuple[str, dict[str, object]]]:
        async with NaoqiBridge(config) as bridge:
            robot = fake(bridge)
        return [c for c in robot.commands if "camera" in c[0]]

    assert asyncio.run(run()) == [
        ("subscribe_camera", {"camera": "bottom", "resolution": "vga", "fps": 5}),
        ("unsubscribe_camera", {"camera": "bottom"}),
    ]


def test_a_failing_camera_keeps_its_last_frame_warns_once_and_recovers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(camera_module, "CAMERA_DOWN_S", 0.1)

    async def run() -> tuple[int, int, int]:
        async with NaoqiBridge(TOP_ONLY) as bridge:
            robot = fake(bridge)
            feed = bridge.cameras["top"]
            await feed.wait_for(lambda _: True)
            working = robot.read_camera

            def broken(camera: object) -> CameraRead | None:
                raise RuntimeError("camera unplugged")

            robot.read_camera = broken  # type: ignore[method-assign]
            await asyncio.sleep(0.05)
            kept = feed.latest()
            assert kept is not None
            await asyncio.sleep(0.3)  # well past CAMERA_DOWN_S
            assert feed.latest() is kept  # the last frame stays published
            robot.read_camera = working  # type: ignore[method-assign]
            recovered = await feed.wait_for(lambda f: f.frame_id > kept.frame_id)
            return kept.frame_id, recovered.frame_id, feed.published_count

    with caplog.at_level(logging.DEBUG, logger="naoqi_bridge.camera"):
        kept, recovered, _ = asyncio.run(run())
    assert recovered > kept
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "every read has failed" in warnings[0].message
    assert any("reads work again" in r.message for r in caplog.records)


def test_a_camera_serving_no_new_frame_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(camera_module, "CAMERA_DOWN_S", 0.1)

    async def run() -> int:
        async with NaoqiBridge(TOP_ONLY) as bridge:
            fake(bridge).camera_period_s = None  # a camera nothing feeds
            await bridge.cameras["top"].wait_for(lambda _: True)
            await asyncio.sleep(0.4)
            return bridge.cameras["top"].published_count

    with caplog.at_level(logging.WARNING, logger="naoqi_bridge.camera"):
        published = asyncio.run(run())
    assert published == 1
    warnings = [r.message for r in caplog.records]
    assert len(warnings) == 1 and "top camera: no new frame" in warnings[0]


def test_the_pull_never_exceeds_the_configured_rate():
    config = NaoqiBridgeConfig(
        streams=StreamSettings(
            cameras=CameraStreams(
                top=CameraStream(enabled=True, resolution="qqvga", fps=10)
            )
        )
    )

    async def run() -> int:
        async with NaoqiBridge(config) as bridge:
            fake(bridge).camera_period_s = 0.001  # the fake could go much faster
            feed = bridge.cameras["top"]
            await feed.wait_for(lambda _: True)
            start = feed.published_count
            await asyncio.sleep(0.5)
            return feed.published_count - start

    assert 3 <= asyncio.run(run()) <= 6  # about 5 in half a second at 10 fps


def test_a_frame_carries_its_pixels_pose_and_field_of_view():
    async def run() -> CameraFrame:
        async with NaoqiBridge(TOP_ONLY) as bridge:
            return await bridge.cameras["top"].wait_for(lambda _: True)

    frame = asyncio.run(run())
    assert (frame.camera, frame.width, frame.height) == ("top", 160, 120)
    image = frame.image
    assert image.shape == (120, 160, 3) and image.dtype == np.uint8
    assert image.tobytes() == frame.data
    assert not image.flags.writeable
    assert image[0, -1, 0] == 255  # blue ramp, BGR
    assert frame.camera_transform == FAKE_CAMERA_TRANSFORMS["top"]
    assert frame.fov == FAKE_CAMERA_FOV
    assert "data" not in repr(frame)  # a frame's repr doesn't dump its pixels


def test_a_session_without_cameras_imports_neither_numpy_nor_pillow():
    script = (
        "import asyncio, sys\n"
        "from naoqi_bridge import NaoqiBridge\n"
        "from naoqi_bridge import naoqi_websocket_server\n"
        "async def run():\n"
        "    async with NaoqiBridge():\n"
        "        pass\n"
        "asyncio.run(run())\n"
        "print(sorted(m for m in ('numpy', 'PIL') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
