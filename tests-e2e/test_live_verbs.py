"""Live, safe level: the bridge's verbs that don't move the limbs, on the target.

Run explicitly: `uv run pytest tests-e2e/test_live_verbs.py` (a sim), or
`NAOQI_E2E_TARGET=real NAOQI_E2E_IP=192.168.1.42 uv run pytest tests-e2e/test_live_verbs.py`.
"""

import asyncio
import time

import pytest
from support import live_config, live_session

from naoqi_bridge import CommandFailedError, MotorsOffError

pytest.importorskip("qi")

EYE_COLORS = ("white", "red", "green", "blue", "yellow", "magenta", "cyan")
LONG_SENTENCE = (
    "This is a rather long sentence, spoken by a live test, which keeps going on "
    "and on so that there is plenty of time to interrupt it before it ends."
)


def test_say_speaks_in_the_language_it_was_given():
    async def run() -> float:
        async with live_session(live_config()) as bridge:
            await bridge.set_tts_language("English")
            started = time.monotonic()
            await bridge.say("Hello, I am running a live test.")
            return time.monotonic() - started

    # say returns once spoken, not once queued: a sentence takes real time.
    assert asyncio.run(run()) > 0.5


def test_stop_say_ends_a_long_say_early():
    async def run() -> tuple[float, float]:
        async with live_session(live_config()) as bridge:
            await bridge.set_tts_language("English")
            started = time.monotonic()
            await bridge.say(LONG_SENTENCE)
            full = time.monotonic() - started
            saying = asyncio.create_task(bridge.say(LONG_SENTENCE))
            await asyncio.sleep(1.0)
            started = time.monotonic()
            await bridge.stop_say()
            # Ended by the stop, whether Naoqi reports it as a return or an error.
            async with asyncio.timeout(2.0):
                await asyncio.gather(saying, return_exceptions=True)
            return full, time.monotonic() - started

    full, after_stop = asyncio.run(run())
    assert full > 3.0  # the sentence is long enough for the test to mean something
    assert after_stop < 1.5


def test_every_documented_eye_color_is_accepted():
    async def run() -> None:
        async with live_session(live_config()) as bridge:
            for color in EYE_COLORS:
                await bridge.change_eyes_color(color)  # CommandFailedError fails it

    asyncio.run(run())


def test_basic_awareness_starts_and_stops():
    async def run() -> None:
        async with live_session(live_config()) as bridge:
            await bridge.set_basic_awareness_state(True, "Unengaged", "Head")
            await asyncio.sleep(1.0)
            await bridge.set_basic_awareness_state(False, "Unengaged", "Head")

    asyncio.run(run())


def test_an_unknown_id_names_the_robots_own_catalog():
    async def run() -> tuple[str, list[str]]:
        async with live_session(live_config()) as bridge:
            ids = [d.id for d in bridge.get_dance_behaviors()]
            with pytest.raises(ValueError) as raised:
                await bridge.dance("no-such-dance")
            return str(raised.value), ids

    message, ids = asyncio.run(run())
    assert message.startswith("unknown dance 'no-such-dance' (known: ")
    assert all(dance_id in message for dance_id in ids)


def test_a_body_verb_at_rest_says_to_wake_the_robot_first():
    async def run() -> None:
        async with live_session(live_config()) as bridge:
            if bridge.robot.is_awake():
                pytest.skip("the motors are on; this safe test won't move the robot")
            with pytest.raises(MotorsOffError, match="call wake_up"):
                await bridge.stand_up()

    asyncio.run(run())


def test_a_verb_naoqi_rejects_comes_back_as_command_failed():
    async def run() -> None:
        async with live_session(live_config()) as bridge:
            with pytest.raises(CommandFailedError) as raised:
                await bridge.set_tts_language("Klingon")
            assert raised.value.__cause__ is not None  # Naoqi's own error, chained

    asyncio.run(run())
