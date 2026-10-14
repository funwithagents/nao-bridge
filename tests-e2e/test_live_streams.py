"""Live: the robot's streams. Joints and audio at the safe level, touch at the
interactive level (someone at the robot touches its head when asked).

On the target (a sim by default, or the robot at NAOQI_E2E_IP); needs `qi`. The touch
test needs a robot, NAOQI_E2E_INTERACTIVE=1, and `-s` to see its prompt.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import TYPE_CHECKING

import numpy as np
import pytest
from support import MEASUREMENTS, live_config, live_session, require_interactive

if TYPE_CHECKING:
    from naoqi_sim import NaoqiSim

from naoqi_bridge import (
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


def test_a_sound_played_into_the_sims_microphone_reaches_audio_input(
    live_sim: NaoqiSim | None,
):
    # Drives the sim itself: a 440 Hz tone into naoqi-sim's fake microphone must come
    # out of the bridge's audio stream (specs/testing.md "Live tier: the target").
    if live_sim is None:
        pytest.skip("plays into naoqi-sim's microphone: the sim target only")
    sim = live_sim
    rate = 16000
    tone = (8000 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype(np.int16)
    config = live_config(
        StreamSettings(audio=AudioStream(enabled=True, channel="front"))
    )

    async def run() -> np.ndarray:
        async with live_session(config) as bridge:
            chunks: list[bytes] = []
            played = 0.0
            async with asyncio.timeout(10.0):
                async for chunk in bridge.audio_input():
                    if not played:  # the stream runs: play into it
                        sim.fake_audio.play(tone, rate)
                        played = time.monotonic()
                    chunks.append(chunk)
                    if time.monotonic() - played >= 2.0:
                        break
            return np.frombuffer(b"".join(chunks), "<i2")

    samples = asyncio.run(run())
    assert np.abs(samples).max() > 1000  # heard, not the quiet room
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    peak = float(np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(spectrum)])
    assert abs(peak - 440) < 20


def test_a_head_touch_reaches_on_touch(capsys: pytest.CaptureFixture[str]):
    require_interactive()
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
