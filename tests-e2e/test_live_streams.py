"""Live: the robot's streams. Joints and audio at the safe level, touch at the
interactive level (someone at the robot touches its head when asked).

Skipped unless NAO_IP is set and `qi` is installed; the touch test also needs
NAO_INTERACTIVE=1, and `-s` to see its prompt.
"""

import asyncio
import math
import time

import pytest
from support import MEASUREMENTS, live_config, live_session, require_flag

from nao_bridge import (
    AudioStream,
    JointsState,
    JointsStream,
    StreamSettings,
    TouchEvent,
    TouchStream,
)

pytest.importorskip("qi")


def test_joints_are_sampled_from_the_robot():
    config = live_config(
        StreamSettings(joints=JointsStream(enabled=True, period_s=0.1))
    )

    async def run() -> tuple[JointsState, JointsState]:
        async with live_session(config) as bridge:
            async with asyncio.timeout(5.0):
                first = await bridge.joints.wait_for(lambda s: s is not None)
                assert first is not None
                later = await bridge.joints.wait_for(
                    lambda s: s is not None and s.ts > first.ts
                )
                assert later is not None
            return first, later

    first, later = asyncio.run(run())
    assert "HeadYaw" in first.names
    assert len(first.angles) == len(first.names)
    assert all(abs(angle) <= math.pi for angle in first.angles)  # radians
    assert later.names == first.names


def test_audio_arrives_at_16_khz_mono():
    config = live_config(
        StreamSettings(audio=AudioStream(enabled=True, channel="front"))
    )

    async def run() -> tuple[int, float, int, int]:
        async with live_session(config) as bridge:
            received = 0
            started = 0.0
            async with asyncio.timeout(5.0):
                async for chunk in bridge.audio_input():
                    if not started:
                        started = time.monotonic()  # count from the first chunk
                        continue
                    received += len(chunk)
                    if time.monotonic() - started >= 2.0:
                        break
            elapsed = time.monotonic() - started
            latest = bridge.mic.latest()
            assert latest is not None
            return received // 2, elapsed, latest.channels, latest.samples_per_channel

    samples, elapsed, channels, chunk_samples = asyncio.run(run())
    rate = samples / elapsed
    # Recorded for specs/microphone.md's open question (the real chunk size).
    MEASUREMENTS.append(("audio chunk at 16 kHz", f"{chunk_samples} samples"))
    assert channels == 1
    assert 12000 < rate < 20000  # about 16 kHz, give or take a chunk at the edges


def test_a_head_touch_reaches_on_touch(capsys: pytest.CaptureFixture[str]):
    require_flag("NAO_INTERACTIVE")
    config = live_config(StreamSettings(touch=TouchStream(enabled=True)))

    async def run() -> TouchEvent:
        async with live_session(config) as bridge:
            touched: asyncio.Queue[TouchEvent] = asyncio.Queue()
            bridge.on_touch.subscribe(touched.put_nowait)
            await bridge.change_eyes_color("green")  # the cue, with the prompt
            with capsys.disabled():
                print("\n>>> Touch the FRONT of Nao's head within 20 s")
            async with asyncio.timeout(20.0):
                while True:
                    event = await touched.get()
                    if event.part == "FrontTactilTouched" and event.touched:
                        return event

    event = asyncio.run(run())
    assert (event.part, event.touched) == ("FrontTactilTouched", True)
