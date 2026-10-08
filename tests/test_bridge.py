"""NaoBridge (specs/bridge.md) on the ``fake`` backend: lifecycle, the catalog
classifier, verbs, running-item tracking and stop semantics, and the streams.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from nao_bridge.bridge import (
    BridgeError,
    JointsState,
    NaoBridge,
    TouchEvent,
    build_catalog,
)
from nao_bridge.config import (
    AudioStream,
    JointsStream,
    NaoBridgeConfig,
    StreamSettings,
    TouchStream,
)
from nao_bridge.robot import FakeNaoRobot

ALL_STREAMS = NaoBridgeConfig(
    streams=StreamSettings(
        touch=TouchStream(enabled=True),
        joints=JointsStream(enabled=True, period_s=0.02),
        audio=AudioStream(enabled=True, channel="left"),
    )
)


def fake(bridge: NaoBridge) -> FakeNaoRobot:
    robot = bridge.robot
    assert isinstance(robot, FakeNaoRobot)
    return robot


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


# --- Lifecycle ----------------------------------------------------------------


def test_async_with_connects_then_closes_the_robot():
    async def run() -> tuple[FakeNaoRobot, bool, bool]:
        async with NaoBridge("fake") as bridge:
            robot = fake(bridge)
            connected_inside = robot.connected
        return robot, connected_inside, bridge.running

    robot, connected_inside, running_after = asyncio.run(run())
    assert connected_inside
    assert not robot.connected
    assert not running_after


def test_robot_is_only_reachable_while_running():
    bridge = NaoBridge("fake")
    with pytest.raises(BridgeError):
        _ = bridge.robot


def test_starting_twice_is_an_error_and_restart_after_stop_works():
    async def run() -> None:
        bridge = NaoBridge("fake")
        await bridge.start()
        with pytest.raises(BridgeError):
            await bridge.start()
        await bridge.stop()
        await bridge.stop()  # no-op
        await bridge.start()
        assert await bridge.say("again")
        await bridge.stop()

    asyncio.run(run())


def test_verbs_return_false_when_not_running():
    bridge = NaoBridge("fake")
    assert asyncio.run(bridge.say("hello")) is False
    assert asyncio.run(bridge.wake_up()) is False


# --- Catalog ------------------------------------------------------------------


def test_catalog_classifies_the_package_list():
    catalog = build_catalog(FakeNaoRobot().list_packages())

    assert set(catalog.dances) == {
        "caravan-palace-se",
        "eagle-dance",
        "gangnam-style",
        "thriller-dance",
    }
    # System packages, dances and dialog packages are not apps.
    assert set(catalog.apps) == {
        "follow-me",
        "presentation",
        "soccer-demonstration",
        "walktotheball",
    }
    assert catalog.dances["eagle-dance"].localized_name.fr_FR == "La danse de l'aigle"

    happy = {b.behavior_name for b in catalog.reactions["Happy"]}
    assert happy == {
        "animations/Stand/Emotions/Positive/Happy_1",
        "animations/Stand/Emotions/Positive/Happy_2",
    }  # the Sit/ emotion is left out
    assert [b.behavior_name for b in catalog.reactions["HeadTouched"]] == [
        "dialog_touch/animations/head_touched"
    ]

    up_left = catalog.body_actions["UpLArm"]
    assert up_left.description == "Raise left arm"
    assert up_left.behavior_name == "dialog_move_arms/animations/UpLArm"
    assert catalog.body_actions["StretchBothArms"].description == "Stretch both arms"


def test_catalog_skips_malformed_packages():
    catalog = build_catalog(
        [{"uuid": "broken"}, {"uuid": "half", "elems": {"names": {}}}]
    )
    assert catalog.dances == {} and catalog.apps == {} and catalog.body_actions == {}
    assert all(not behaviors for behaviors in catalog.reactions.values())


def test_getters_serve_the_robot_catalog_once_started():
    async def run() -> tuple[int, int, list[str]]:
        bridge = NaoBridge("fake")
        before = len(bridge.get_dance_behaviors())
        async with bridge:
            return (
                before,
                len(bridge.get_dance_behaviors()),
                bridge.get_expressive_reaction_types(),
            )

    before, after, reaction_types = asyncio.run(run())
    assert (before, after) == (0, 4)
    assert reaction_types == ["Happy", "Proud", "Laugh", "Sad", "HeadTouched"]


# --- Verbs --------------------------------------------------------------------


def test_verbs_drive_the_robot():
    async def run() -> list[tuple[str, dict[str, Any]]]:
        async with NaoBridge("fake") as bridge:
            robot = fake(bridge)
            robot.commands.clear()
            assert await bridge.set_tts_language("French")
            assert await bridge.say("Bonjour")
            assert await bridge.stand_up()
            assert await bridge.change_eyes_color("cyan")
            assert await bridge.set_breathing_enabled(True, "Body")
            return list(robot.commands)

    assert asyncio.run(run()) == [
        ("set_language", {"language": "French"}),
        ("say", {"text": "Bonjour"}),
        ("go_to_posture", {"posture": "Stand", "speed": 0.8, "max_tries": 3}),
        ("fade_eyes", {"color": "cyan"}),
        ("set_breathing", {"chain_name": "Body", "enabled": True}),
    ]


def test_a_failed_posture_is_reported():
    async def run() -> bool:
        async with NaoBridge("fake") as bridge:
            fake(bridge).posture_succeeds = False
            return await bridge.sit_down()

    assert asyncio.run(run()) is False


def test_a_robot_error_becomes_false_not_an_exception(monkeypatch: pytest.MonkeyPatch):
    def broken_say(text: str) -> None:
        raise RuntimeError("ALAnimatedSpeech is gone")

    async def run() -> bool:
        async with NaoBridge("fake") as bridge:
            monkeypatch.setattr(fake(bridge), "say", broken_say)
            return await bridge.say("hello")

    assert asyncio.run(run()) is False


def test_unknown_catalog_ids_are_rejected():
    async def run() -> list[bool]:
        async with NaoBridge("fake") as bridge:
            return [
                await bridge.dance("macarena"),
                await bridge.run_app("nope"),
                await bridge.body_action("Wave"),
                await bridge.expressive_reaction("Angry"),
                await bridge.stop_dance("macarena"),
            ]

    assert asyncio.run(run()) == [False] * 5


def test_a_dance_runs_the_behavior_and_untracks_it_when_done():
    async def run() -> tuple[bool, list[str], list[tuple[str, dict[str, Any]]]]:
        async with NaoBridge("fake") as bridge:
            ok = await bridge.dance("gangnam-style")
            return ok, list(bridge.current_dances), fake(bridge).commands

    ok, current, commands = asyncio.run(run())
    assert ok
    assert current == []
    assert ("run_behavior", {"name": "gangnam-style"}) in commands


def test_stop_dance_ends_a_running_dance_but_not_an_idle_one():
    async def run() -> tuple[bool, bool, bool]:
        async with NaoBridge("fake") as bridge:
            fake(bridge).behavior_duration_s = 5.0
            idle_stop = await bridge.stop_dance("eagle-dance")
            dancing = asyncio.create_task(bridge.dance("eagle-dance"))
            await wait_until(lambda: "eagle-dance" in fake(bridge).running_behaviors)
            stopped = await bridge.stop_dance("eagle-dance")
            async with asyncio.timeout(1.0):
                danced = await dancing
            return idle_stop, stopped, danced

    assert asyncio.run(run()) == (False, True, True)


def test_stop_expressive_reaction_stops_the_behavior_that_is_playing():
    async def run() -> tuple[bool, str, list[tuple[str, dict[str, Any]]], set[str]]:
        async with NaoBridge("fake") as bridge:
            robot = fake(bridge)
            robot.behavior_duration_s = 5.0
            reacting = asyncio.create_task(bridge.expressive_reaction("Happy"))
            await wait_until(lambda: "Happy" in bridge.current_expressive_reactions)
            playing = bridge.current_expressive_reactions["Happy"]
            await wait_until(lambda: playing in robot.running_behaviors)
            stopped = await bridge.stop_expressive_reaction("Happy")
            async with asyncio.timeout(1.0):
                await reacting
            happy = {b.behavior_name for b in bridge._catalog.reactions["Happy"]}
            return stopped, playing, robot.commands, happy

    stopped, playing, commands, happy = asyncio.run(run())
    assert stopped
    assert playing in happy
    assert ("stop_behavior", {"name": playing}) in commands


def test_stop_releases_long_running_behaviors_and_clears_tracking():
    async def run() -> tuple[bool, list[str]]:
        bridge = NaoBridge("fake")
        await bridge.start()
        fake(bridge).behavior_duration_s = 5.0
        app = asyncio.create_task(bridge.run_app("follow-me"))
        await wait_until(lambda: bridge.current_apps == ["follow-me"])
        await bridge.stop()
        async with asyncio.timeout(1.0):
            await app
        return bridge.running, bridge.current_apps

    assert asyncio.run(run()) == (False, [])


# --- Config -------------------------------------------------------------------


def test_construction_from_a_config_a_backend_string_or_nothing():
    assert NaoBridge().backend == "fake"
    assert NaoBridge("fake").config == NaoBridgeConfig()
    from_dict = NaoBridge.from_dict({"streams": {"touch": {"enabled": True}}})
    assert from_dict.config.streams.touch.enabled
    assert NaoBridge.from_json('{"backend": "fake"}').backend == "fake"


# --- Streams ------------------------------------------------------------------


def test_disabled_streams_are_not_subscribed_and_their_apis_refuse():
    async def run() -> list[str]:
        async with NaoBridge("fake") as bridge:
            with pytest.raises(BridgeError, match="joints"):
                _ = bridge.joints
            with pytest.raises(BridgeError, match="audio"):
                bridge.audio_input()
            return [name for name, _ in fake(bridge).commands]

    assert asyncio.run(run()) == ["connect"]


def test_enabled_streams_are_subscribed_at_start_and_released_at_stop():
    async def run() -> list[tuple[str, dict[str, Any]]]:
        async with NaoBridge(ALL_STREAMS) as bridge:
            robot = fake(bridge)
        return robot.commands

    commands = asyncio.run(run())
    assert ("subscribe_touch", {}) in commands
    assert ("subscribe_audio", {"channel": "left"}) in commands
    assert commands[-3:] == [
        ("unsubscribe_audio", {}),
        ("unsubscribe_touch", {}),
        ("close", {}),
    ]


def test_touch_events_are_emitted_on_the_event_loop():
    async def run() -> list[tuple[TouchEvent, bool]]:
        received: list[tuple[TouchEvent, bool]] = []
        async with NaoBridge(ALL_STREAMS) as bridge:
            loop = asyncio.get_running_loop()

            def on_touch(event: TouchEvent) -> None:
                received.append((event, asyncio.get_running_loop() is loop))

            bridge.on_touch.subscribe(on_touch)
            fake(bridge).touch("FrontTactilTouched", 1.0)
            fake(bridge).touch("FrontTactilTouched", 0.0)
            await wait_until(lambda: len(received) == 2)
        return received

    assert asyncio.run(run()) == [
        (TouchEvent("FrontTactilTouched", True), True),
        (TouchEvent("FrontTactilTouched", False), True),
    ]


def test_joints_are_published_while_running_and_reset_at_stop():
    async def run() -> tuple[
        JointsState | None, JointsState | None, JointsState | None
    ]:
        bridge = NaoBridge(ALL_STREAMS)
        before = bridge.joints.value
        await bridge.start()
        sample = await asyncio.wait_for(
            bridge.joints.wait_for(lambda s: s is not None), 1.0
        )
        await bridge.stop()
        return before, sample, bridge.joints.value

    before, sample, after = asyncio.run(run())
    assert before is None and after is None
    assert sample is not None
    assert (sample.names, sample.angles) == (("HeadYaw", "HeadPitch"), (0.0, 0.1))


def test_audio_input_streams_the_robot_microphone_to_several_subscribers():
    async def run() -> tuple[int, int, bool, bool]:
        async with NaoBridge(ALL_STREAMS) as bridge:
            fake(bridge).audio_chunk_s = 0.01

            async def count(n: int) -> int:
                got = 0
                async for chunk in bridge.audio_input():
                    # silence, int16 mono (the first chunks may predate the 10 ms pace)
                    assert chunk and chunk == bytes(len(chunk))
                    got += 1
                    if got == n:
                        break
                return got

            first, second = await asyncio.wait_for(
                asyncio.gather(count(5), count(5)), 2.0
            )
            live = bridge.mic.latest() is not None
        with pytest.raises(BridgeError, match="not running"):
            bridge.audio_input()
        return first, second, live, bridge.mic.latest() is None

    assert asyncio.run(run()) == (5, 5, True, True)
