"""NaoqiBridge (specs/bridge.md) on the ``fake`` backend: lifecycle, the catalog
classifier, verbs, running-item tracking and stop semantics, and the streams.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Collection, Coroutine
from typing import Any

import pytest

from naoqi_bridge import (
    BridgeError,
    CommandFailedError,
    MotorsOffError,
    NotPlayingError,
    NotRunningError,
)
from naoqi_bridge.bridge import JointsState, NaoqiBridge, TouchEvent, build_catalog
from naoqi_bridge.config import (
    AudioStream,
    JointsStream,
    NaoqiBridgeConfig,
    StreamSettings,
    TouchStream,
)
from naoqi_bridge.fake_robot import JOINT_NAMES, POSTURE_ANGLES, FakeNaoqiRobot
from naoqi_bridge.robot import RobotConnectionError

ALL_STREAMS = NaoqiBridgeConfig(
    streams=StreamSettings(
        touch=TouchStream(enabled=True),
        joints=JointsStream(enabled=True, period_s=0.02),
        audio=AudioStream(enabled=True, channel="left"),
    )
)


def fake(bridge: NaoqiBridge) -> FakeNaoqiRobot:
    robot = bridge.robot
    assert isinstance(robot, FakeNaoqiRobot)
    return robot


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


# --- Lifecycle ----------------------------------------------------------------


def test_async_with_connects_then_closes_the_robot():
    async def run() -> tuple[FakeNaoqiRobot, bool, bool]:
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            connected_inside = robot.connected
        return robot, connected_inside, bridge.running

    robot, connected_inside, running_after = asyncio.run(run())
    assert connected_inside
    assert not robot.connected
    assert not running_after


def test_robot_is_only_reachable_while_running():
    bridge = NaoqiBridge("fake")
    with pytest.raises(NotRunningError):
        _ = bridge.robot


def test_starting_twice_is_an_error_and_restart_after_stop_works():
    async def run() -> None:
        bridge = NaoqiBridge("fake")
        await bridge.start()
        with pytest.raises(BridgeError):
            await bridge.start()
        await bridge.stop()
        await bridge.stop()  # no-op
        await bridge.start()
        await bridge.say("again")
        await bridge.stop()

    asyncio.run(run())


def test_verbs_raise_not_running_when_the_bridge_is_stopped():
    bridge = NaoqiBridge("fake")
    with pytest.raises(NotRunningError, match="call start"):
        asyncio.run(bridge.say("hello"))
    # Checked before the catalog: a stopped bridge doesn't call an id unknown.
    with pytest.raises(NotRunningError):
        asyncio.run(bridge.dance("macarena"))


# --- Catalog ------------------------------------------------------------------


def test_catalog_classifies_the_package_list():
    catalog = build_catalog(FakeNaoqiRobot().list_packages())

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


def test_catalog_tolerates_sub_behaviors_without_names_or_tags():
    bare = {
        "uuid": "dialog_move_arms",
        "elems": {
            "names": {"en_US": "Move arms"},
            "descriptions": {},
            "contents": {"behaviors": [{"path": "animations/UpRArm"}]},
        },
    }
    catalog = build_catalog([bare])
    assert catalog.body_actions["UpRArm"].description == "Raise right arm"


def test_getters_serve_the_robot_catalog_once_started():
    async def run() -> tuple[int, int, list[str]]:
        bridge = NaoqiBridge("fake")
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
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            await bridge.wake_up()
            robot.commands.clear()
            await bridge.set_tts_language("French")
            await bridge.say("Bonjour")
            await bridge.stand_up()
            await bridge.change_eyes_color("cyan")
            await bridge.set_breathing_enabled(True, "Body")
            return list(robot.commands)

    assert asyncio.run(run()) == [
        ("set_language", {"language": "French"}),
        ("say", {"text": "Bonjour"}),
        ("go_to_posture", {"posture": "Stand", "speed": 0.8, "max_tries": 3}),
        ("fade_eyes", {"color": "cyan"}),
        ("set_breathing", {"chain_name": "Body", "enabled": True}),
    ]


def test_a_posture_not_reached_raises_command_failed():
    async def run() -> None:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            fake(bridge).posture_succeeds = False
            await bridge.sit_down()

    with pytest.raises(CommandFailedError, match="sit_down failed: .*Sit posture"):
        asyncio.run(run())


def test_a_robot_error_is_raised_with_its_reason_and_chained(
    monkeypatch: pytest.MonkeyPatch,
):
    naoqi_error = RuntimeError("ALAnimatedSpeech is gone")

    def broken_say(text: str) -> None:
        raise naoqi_error

    async def run() -> None:
        async with NaoqiBridge("fake") as bridge:
            monkeypatch.setattr(fake(bridge), "say", broken_say)
            await bridge.say("hello")

    with pytest.raises(CommandFailedError) as raised:
        asyncio.run(run())
    assert str(raised.value) == "say failed: ALAnimatedSpeech is gone"
    assert raised.value.__cause__ is naoqi_error


def test_verbs_that_move_the_body_need_the_motors_on():
    async def run() -> tuple[list[str], list[tuple[str, dict[str, Any]]]]:
        messages: list[str] = []
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            robot.commands.clear()
            for verb in (
                bridge.stand_up(),
                bridge.sit_down(),
                bridge.set_breathing_enabled(True, "Body"),
                bridge.run_behavior("animations/Stand/Emotions/Positive/Happy_1"),
                bridge.dance("eagle-dance"),
                bridge.expressive_reaction("Happy"),
                bridge.body_action("UpLArm"),
                bridge.run_app("follow-me"),
            ):
                with pytest.raises(MotorsOffError) as raised:
                    await verb
                messages.append(str(raised.value))
            # Nothing was sent, and nothing is left tracked as playing.
            assert robot.commands == []
            assert bridge.current_dances == () and bridge.current_behaviors == ()
            # Verbs that don't move the body work with the motors off.
            await bridge.say("I am resting")
            await bridge.change_eyes_color("blue")
            await bridge.set_breathing_enabled(False, "Body")
            return messages, list(robot.commands)

    messages, commands = asyncio.run(run())
    assert [m.split(":")[0] for m in messages] == [
        "stand_up",
        "sit_down",
        "set_breathing_enabled",
        "run_behavior",
        "dance",
        "expressive_reaction",
        "body_action",
        "run_app",
    ]
    assert messages[0] == "stand_up: the motors are off; call wake_up() first"
    assert [name for name, _ in commands] == ["say", "fade_eyes", "set_breathing"]


def test_the_motors_are_asked_each_time_not_remembered():
    async def run() -> None:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            await bridge.stand_up()
            await bridge.rest()
            with pytest.raises(MotorsOffError):
                await bridge.stand_up()
            await bridge.wake_up()
            fake(bridge).awake = False  # e.g. the fall manager cut the motors
            with pytest.raises(MotorsOffError):
                await bridge.dance("eagle-dance")
            # An unknown id is still reported as such, motors on or off.
            with pytest.raises(ValueError, match="unknown dance"):
                await bridge.dance("macarena")

    asyncio.run(run())


def test_unknown_catalog_ids_raise_value_error_naming_the_known_ones():
    async def run() -> list[str]:
        messages: list[str] = []
        async with NaoqiBridge("fake") as bridge:
            for verb in (
                bridge.dance("macarena"),
                bridge.run_app("nope"),
                bridge.body_action("Wave"),
                bridge.expressive_reaction("Angry"),
                bridge.stop_dance("macarena"),
            ):
                with pytest.raises(ValueError) as raised:
                    await verb
                messages.append(str(raised.value))
        return messages

    dance, app, body_action, reaction, stop = asyncio.run(run())
    assert dance.startswith("unknown dance 'macarena' (known: caravan-palace-se, ")
    assert "follow-me" in app
    assert "UpLArm" in body_action
    assert reaction == (
        "unknown reaction type 'Angry' (known: Happy, Proud, Laugh, Sad, HeadTouched)"
    )
    assert stop == dance


def test_a_reaction_type_without_behaviors_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
):
    packages = FakeNaoqiRobot().list_packages()
    for package in packages:  # a robot whose animations package has no Proud emotion
        behaviors = package["elems"]["contents"]["behaviors"]
        behaviors[:] = [
            b for b in behaviors if "proud" not in b["langToTags"].get("en_US", [])
        ]
    monkeypatch.setattr(FakeNaoqiRobot, "list_packages", lambda self: packages)

    async def run() -> None:
        async with NaoqiBridge("fake") as bridge:
            assert "Proud" in bridge.get_expressive_reaction_types()
            await bridge.expressive_reaction("Proud")

    with pytest.raises(ValueError, match="no behaviors installed .* 'Proud'"):
        asyncio.run(run())


def test_a_dance_runs_the_behavior_and_untracks_it_when_done():
    async def run() -> tuple[list[str], list[tuple[str, dict[str, Any]]]]:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            await bridge.dance("gangnam-style")
            return list(bridge.current_dances), fake(bridge).commands

    current, commands = asyncio.run(run())
    assert current == []
    assert ("run_behavior", {"name": "gangnam-style"}) in commands


def test_stop_dance_ends_a_running_dance_but_not_an_idle_one():
    async def run() -> list[str]:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            fake(bridge).behavior_duration_s = 5.0
            with pytest.raises(NotPlayingError, match="dance 'eagle-dance' is not"):
                await bridge.stop_dance("eagle-dance")
            dancing = asyncio.create_task(bridge.dance("eagle-dance"))
            await wait_until(lambda: "eagle-dance" in fake(bridge).running_behaviors)
            await bridge.stop_dance("eagle-dance")
            async with asyncio.timeout(1.0):
                await dancing  # ends normally, stopped well before its 5 s
            return fake(bridge).running_behaviors

    assert asyncio.run(run()) == []


def test_stop_dance_landing_before_naoqi_starts_the_dance_still_stops_it(
    monkeypatch: pytest.MonkeyPatch,
):
    run_behavior = FakeNaoqiRobot.run_behavior

    def late_run(self: FakeNaoqiRobot, name: str) -> None:
        time.sleep(0.2)  # Naoqi hasn't started it yet: a first stop finds nothing
        run_behavior(self, name)

    async def run() -> tuple[float, list[str]]:
        monkeypatch.setattr(FakeNaoqiRobot, "run_behavior", late_run)
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            fake(bridge).behavior_duration_s = 5.0
            dancing = asyncio.create_task(bridge.dance("eagle-dance"))
            await wait_until(lambda: "eagle-dance" in bridge.current_dances)
            started = time.monotonic()
            await bridge.stop_dance("eagle-dance")
            async with asyncio.timeout(1.0):
                await dancing  # stopped, not played for its 5 s
            return time.monotonic() - started, command_names(fake(bridge))

    elapsed, commands = asyncio.run(run())
    assert elapsed < 1.0  # stop_dance returned once the dance had stopped
    assert commands.count("stop_behavior") == 2  # the first stop was re-sent


def test_stop_expressive_reaction_stops_the_behavior_that_is_playing():
    async def run() -> tuple[str, list[tuple[str, dict[str, Any]]], set[str]]:
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            await bridge.wake_up()
            robot.behavior_duration_s = 5.0
            reacting = asyncio.create_task(bridge.expressive_reaction("Happy"))
            await wait_until(lambda: "Happy" in bridge.current_expressive_reactions)
            playing = bridge.current_expressive_reactions["Happy"]
            await wait_until(lambda: playing in robot.running_behaviors)
            await bridge.stop_expressive_reaction("Happy")
            async with asyncio.timeout(1.0):
                await reacting
            catalog = build_catalog(robot.list_packages())
            happy = {b.behavior_name for b in catalog.reactions["Happy"]}
            return playing, robot.commands, happy

    playing, commands, happy = asyncio.run(run())
    assert playing in happy
    assert ("stop_behavior", {"name": playing}) in commands


@pytest.mark.fake_behavior_durations
def test_on_a_fresh_fake_behaviors_run_until_stopped():
    async def run() -> tuple[float, list[str], float]:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            duration = fake(bridge).behavior_duration_s
            started = time.monotonic()
            dancing = asyncio.create_task(bridge.dance("eagle-dance"))
            await asyncio.sleep(0.2)
            running = list(bridge.current_dances)
            await bridge.stop_dance("eagle-dance")
            await asyncio.wait_for(dancing, 1.0)
            return duration, running, time.monotonic() - started

    duration, running, elapsed = asyncio.run(run())
    assert duration == 5.0
    assert running == ["eagle-dance"]  # still dancing after 0.2 s
    assert elapsed < 1.0  # ended by the stop, not by the 5 s


def test_stop_releases_long_running_behaviors_and_clears_tracking():
    async def run() -> tuple[bool, tuple[str, ...]]:
        bridge = NaoqiBridge("fake")
        await bridge.start()
        await bridge.wake_up()
        fake(bridge).behavior_duration_s = 5.0
        app = asyncio.create_task(bridge.run_app("follow-me"))
        await wait_until(lambda: bridge.current_apps == ("follow-me",))
        await bridge.stop()
        async with asyncio.timeout(1.0):
            await app
        return bridge.running, bridge.current_apps

    assert asyncio.run(run()) == (False, ())


# --- Cancellation -------------------------------------------------------------

Verb = Callable[[NaoqiBridge], Coroutine[Any, Any, None]]
Tracking = Callable[[NaoqiBridge], Collection[str]]

SPANNING_BEHAVIOR_VERBS: list[tuple[Verb, Tracking]] = [
    (lambda b: b.dance("eagle-dance"), lambda b: b.current_dances),
    (lambda b: b.body_action("UpLArm"), lambda b: b.current_body_actions),
    (lambda b: b.run_app("follow-me"), lambda b: b.current_apps),
    (lambda b: b.run_behavior("eagle-dance"), lambda b: b.current_behaviors),
    (
        lambda b: b.expressive_reaction("Happy"),
        lambda b: b.current_expressive_reactions,
    ),
]


def command_names(robot: FakeNaoqiRobot) -> list[str]:
    return [name for name, _ in robot.commands]


async def start_dancing(bridge: NaoqiBridge) -> asyncio.Task[None]:
    """Wake the robot and start a 5 s ``eagle-dance``, returned once it's playing."""
    await bridge.wake_up()
    fake(bridge).behavior_duration_s = 5.0
    dancing = asyncio.create_task(bridge.dance("eagle-dance"))
    await wait_until(lambda: "eagle-dance" in fake(bridge).running_behaviors)
    return dancing


async def cancel_and_wait(task: asyncio.Task[None]) -> float:
    """Cancel ``task``, check it ends cancelled, and return how long that took."""
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return time.monotonic() - started


@pytest.mark.parametrize(
    ("verb", "tracking"),
    SPANNING_BEHAVIOR_VERBS,
    ids=["dance", "body_action", "run_app", "run_behavior", "expressive_reaction"],
)
def test_a_cancelled_behavior_verb_stops_its_behavior(verb: Verb, tracking: Tracking):
    async def run() -> tuple[str, float, list[str], Any, Any]:
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            await bridge.wake_up()
            robot.behavior_duration_s = 5.0
            task = asyncio.create_task(verb(bridge))
            await wait_until(
                lambda: bool(robot.running_behaviors) and bool(tracking(bridge))
            )
            playing = robot.running_behaviors[0]
            elapsed = await cancel_and_wait(task)
            return (
                playing,
                elapsed,
                robot.running_behaviors,
                robot.commands,
                tracking(bridge),
            )

    playing, elapsed, running, commands, tracked = asyncio.run(run())
    assert elapsed < 1.0  # stopped, not waited out for 5 s
    assert running == []
    assert ("stop_behavior", {"name": playing}) in commands
    assert not tracked


def test_a_timeout_around_a_dance_stops_it():
    async def run() -> list[str]:
        async with NaoqiBridge("fake") as bridge:
            await bridge.wake_up()
            fake(bridge).behavior_duration_s = 5.0
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.1):
                    await bridge.dance("eagle-dance")
            return fake(bridge).running_behaviors

    assert asyncio.run(run()) == []


def test_a_cancelled_dance_stays_tracked_until_it_has_stopped(
    monkeypatch: pytest.MonkeyPatch,
):
    stop_behavior = FakeNaoqiRobot.stop_behavior

    def slow_stop(self: FakeNaoqiRobot, name: str) -> None:
        time.sleep(0.2)
        stop_behavior(self, name)

    async def run() -> tuple[tuple[str, ...], tuple[str, ...]]:
        monkeypatch.setattr(FakeNaoqiRobot, "stop_behavior", slow_stop)
        async with NaoqiBridge("fake") as bridge:
            dancing = await start_dancing(bridge)
            dancing.cancel()
            await asyncio.sleep(0.05)
            while_stopping = bridge.current_dances
            with pytest.raises(asyncio.CancelledError):
                await dancing
            return while_stopping, bridge.current_dances

    assert asyncio.run(run()) == (("eagle-dance",), ())


def test_a_cancelled_say_stops_the_speech():
    async def run() -> tuple[float, bool, list[str]]:
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            robot.speech_duration_s = 5.0
            saying = asyncio.create_task(bridge.say("A very long story"))
            await wait_until(lambda: robot.speaking)
            elapsed = await cancel_and_wait(saying)
            return elapsed, robot.speaking, command_names(robot)

    elapsed, speaking, commands = asyncio.run(run())
    assert elapsed < 1.0
    assert not speaking
    assert commands[-2:] == ["say", "stop_speech"]


def test_a_cancelled_posture_move_stops_and_raises_only_the_cancel():
    async def run() -> tuple[float, bool, list[str]]:
        async with NaoqiBridge("fake") as bridge:
            robot = fake(bridge)
            await bridge.wake_up()
            robot.posture_duration_s = 5.0
            robot.posture_succeeds = False  # a stopped move hasn't reached Stand
            standing = asyncio.create_task(bridge.stand_up())
            await wait_until(lambda: robot.moving_posture)
            elapsed = await cancel_and_wait(standing)  # not CommandFailedError
            return elapsed, robot.moving_posture, command_names(robot)

    elapsed, moving, commands = asyncio.run(run())
    assert elapsed < 1.0
    assert not moving
    assert commands[-2:] == ["go_to_posture", "stop_posture"]


def test_a_stop_that_finds_nothing_yet_is_sent_again(monkeypatch: pytest.MonkeyPatch):
    stop_behavior = FakeNaoqiRobot.stop_behavior
    stops: list[str] = []

    def stop_missing_the_first_time(self: FakeNaoqiRobot, name: str) -> None:
        stops.append(name)
        if len(stops) == 1:
            self.commands.append(("stop_behavior", {"name": name}))  # too early
        else:
            stop_behavior(self, name)

    async def run() -> list[str]:
        monkeypatch.setattr("naoqi_bridge.bridge.STOP_RETRY_S", 0.05)
        monkeypatch.setattr(
            FakeNaoqiRobot, "stop_behavior", stop_missing_the_first_time
        )
        async with NaoqiBridge("fake") as bridge:
            await cancel_and_wait(await start_dancing(bridge))
            return fake(bridge).running_behaviors

    assert asyncio.run(run()) == []
    assert stops == ["eagle-dance", "eagle-dance"]


def test_a_stop_the_robot_never_confirms_gives_up_in_bounded_time(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def ignored_stop(self: FakeNaoqiRobot, name: str) -> None:
        self.commands.append(("stop_behavior", {"name": name}))

    async def run() -> tuple[float, int, tuple[str, ...]]:
        monkeypatch.setattr("naoqi_bridge.bridge.STOP_RETRY_S", 0.02)
        monkeypatch.setattr(FakeNaoqiRobot, "stop_behavior", ignored_stop)
        async with NaoqiBridge("fake") as bridge:
            elapsed = await cancel_and_wait(await start_dancing(bridge))
            stops = command_names(fake(bridge)).count("stop_behavior")
            return elapsed, stops, bridge.current_dances

    elapsed, stops, tracked = asyncio.run(run())
    assert elapsed < 0.5  # 8 attempts of 20 ms, not the dance's 5 s
    assert stops == 8
    assert tracked == ()
    assert (
        "run_behavior: the robot did not confirm the stop after 8 attempts"
        in caplog.messages
    )


def test_a_failing_stop_is_logged_and_the_caller_still_gets_the_cancel(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def broken_stop(self: FakeNaoqiRobot, name: str) -> None:
        raise RuntimeError("ALBehaviorManager is gone")

    async def run() -> tuple[str, ...]:
        monkeypatch.setattr(FakeNaoqiRobot, "stop_behavior", broken_stop)
        async with NaoqiBridge("fake") as bridge:
            await cancel_and_wait(await start_dancing(bridge))
            return bridge.current_dances

    assert asyncio.run(run()) == ()
    assert "run_behavior: stopping it failed" in caplog.messages


def test_a_second_cancel_does_not_cut_the_stop_short(monkeypatch: pytest.MonkeyPatch):
    stop_behavior = FakeNaoqiRobot.stop_behavior

    def slow_stop(self: FakeNaoqiRobot, name: str) -> None:
        time.sleep(0.1)
        stop_behavior(self, name)

    async def run() -> list[str]:
        monkeypatch.setattr(FakeNaoqiRobot, "stop_behavior", slow_stop)
        async with NaoqiBridge("fake") as bridge:
            dancing = await start_dancing(bridge)
            dancing.cancel()
            await asyncio.sleep(0.02)
            dancing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await dancing
            return fake(bridge).running_behaviors

    assert asyncio.run(run()) == []


def test_a_cancel_during_the_motors_check_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    asked = threading.Event()
    answer = threading.Event()

    def slow_is_awake(self: FakeNaoqiRobot) -> bool:
        asked.set()
        answer.wait(1.0)
        return True

    async def run() -> list[str]:
        monkeypatch.setattr(FakeNaoqiRobot, "is_awake", slow_is_awake)
        async with NaoqiBridge("fake") as bridge:
            dancing = asyncio.create_task(bridge.dance("eagle-dance"))
            await wait_until(asked.is_set)
            await cancel_and_wait(dancing)
            answer.set()
            await asyncio.sleep(0.05)
            return command_names(fake(bridge))

    commands = asyncio.run(run())
    assert "run_behavior" not in commands
    assert "stop_behavior" not in commands


def test_the_session_is_usable_right_after_a_cancel():
    async def run() -> tuple[list[str], bool]:
        async with NaoqiBridge("fake") as bridge:
            await cancel_and_wait(await start_dancing(bridge))
            fake(bridge).behavior_duration_s = 0.0
            await bridge.dance("gangnam-style")
            return command_names(fake(bridge)), fake(bridge).awake

    commands, awake = asyncio.run(run())
    assert commands.count("run_behavior") == 2
    assert "rest" not in commands
    assert awake


def test_a_cancelled_instant_verb_returns_at_once_and_its_command_completes(
    monkeypatch: pytest.MonkeyPatch,
):
    fade_eyes = FakeNaoqiRobot.fade_eyes

    def slow_fade(self: FakeNaoqiRobot, color: str) -> None:
        time.sleep(0.3)
        fade_eyes(self, color)

    async def run() -> tuple[float, list[str]]:
        monkeypatch.setattr(FakeNaoqiRobot, "fade_eyes", slow_fade)
        async with NaoqiBridge("fake") as bridge:
            fading = asyncio.create_task(bridge.change_eyes_color("red"))
            await asyncio.sleep(0.05)
            elapsed = await cancel_and_wait(fading)
            await asyncio.sleep(0.4)
            return elapsed, command_names(fake(bridge))

    elapsed, commands = asyncio.run(run())
    assert elapsed < 0.2
    assert commands.count("fade_eyes") == 1


def test_a_start_cancelled_while_connecting_closes_the_robot(
    monkeypatch: pytest.MonkeyPatch,
):
    connect = FakeNaoqiRobot.connect
    robots: list[FakeNaoqiRobot] = []

    def slow_connect(
        self: FakeNaoqiRobot, cancel: threading.Event | None = None
    ) -> None:
        robots.append(self)
        time.sleep(0.2)  # deaf to the cancel: connects anyway
        connect(self)

    async def run() -> tuple[bool, float]:
        monkeypatch.setattr(FakeNaoqiRobot, "connect", slow_connect)
        bridge = NaoqiBridge("fake")
        starting = asyncio.create_task(bridge.start())
        await asyncio.sleep(0.05)
        elapsed = await cancel_and_wait(starting)
        return bridge.running, elapsed

    running, elapsed = asyncio.run(run())
    assert not running
    assert elapsed >= 0.1  # waited for the connection in flight
    assert command_names(robots[0]) == ["connect", "close"]
    assert not robots[0].connected


def test_a_start_cancelled_while_connecting_gives_up_the_connection(
    monkeypatch: pytest.MonkeyPatch,
):
    robots: list[FakeNaoqiRobot] = []

    def pending_connect(
        self: FakeNaoqiRobot, cancel: threading.Event | None = None
    ) -> None:
        # A silent host: no answer for 5 s, unless the connection is cancelled.
        robots.append(self)
        assert cancel is not None
        cancel.wait(5.0)
        raise RobotConnectionError("connection cancelled")

    async def run() -> tuple[bool, float]:
        monkeypatch.setattr(FakeNaoqiRobot, "connect", pending_connect)
        bridge = NaoqiBridge("fake")
        starting = asyncio.create_task(bridge.start())
        await asyncio.sleep(0.05)
        elapsed = await cancel_and_wait(starting)
        return bridge.running, elapsed

    running, elapsed = asyncio.run(run())
    assert not running
    assert elapsed < 0.5  # not the 5 s the connection would have taken
    assert command_names(robots[0]) == []  # never connected, so nothing to close


def test_a_cancelled_stop_still_runs_every_teardown_step(
    monkeypatch: pytest.MonkeyPatch,
):
    unsubscribe_touch = FakeNaoqiRobot.unsubscribe_touch

    def slow_unsubscribe(self: FakeNaoqiRobot) -> None:
        time.sleep(0.2)
        unsubscribe_touch(self)

    async def run() -> tuple[bool, list[str]]:
        monkeypatch.setattr(FakeNaoqiRobot, "unsubscribe_touch", slow_unsubscribe)
        bridge = NaoqiBridge(
            NaoqiBridgeConfig(streams=StreamSettings(touch=TouchStream(enabled=True)))
        )
        await bridge.start()
        robot = fake(bridge)
        stopping = asyncio.create_task(bridge.stop())
        await asyncio.sleep(0.05)
        await cancel_and_wait(stopping)
        return bridge.running, command_names(robot)

    running, commands = asyncio.run(run())
    assert not running
    assert commands[-2:] == ["unsubscribe_touch", "close"]


# --- Config -------------------------------------------------------------------


def test_construction_from_a_config_a_backend_string_or_nothing():
    assert NaoqiBridge().backend == "fake"
    assert NaoqiBridge("fake").config == NaoqiBridgeConfig()
    from_dict = NaoqiBridge.from_dict({"streams": {"touch": {"enabled": True}}})
    assert from_dict.config.streams.touch.enabled
    assert NaoqiBridge.from_json('{"backend": "fake"}').backend == "fake"


# --- Streams ------------------------------------------------------------------


def test_disabled_streams_are_not_subscribed_and_their_apis_refuse():
    async def run() -> list[str]:
        async with NaoqiBridge("fake") as bridge:
            with pytest.raises(BridgeError, match="joints"):
                _ = bridge.joints
            with pytest.raises(BridgeError, match="audio"):
                bridge.audio_input()
            return [name for name, _ in fake(bridge).commands]

    assert asyncio.run(run()) == ["connect"]


def test_enabled_streams_are_subscribed_at_start_and_released_at_stop():
    async def run() -> list[tuple[str, dict[str, Any]]]:
        async with NaoqiBridge(ALL_STREAMS) as bridge:
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
        async with NaoqiBridge(ALL_STREAMS) as bridge:
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
        bridge = NaoqiBridge(ALL_STREAMS)
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
    # a fake starts at rest, crouched
    assert (sample.names, sample.angles) == (JOINT_NAMES, POSTURE_ANGLES["Crouch"])


def test_joints_follow_the_posture_verbs():
    crouch, stand, sit = (POSTURE_ANGLES[p] for p in ("Crouch", "Stand", "Sit"))

    async def run() -> None:
        async with NaoqiBridge(ALL_STREAMS) as bridge:
            steps = [
                (bridge.wake_up, crouch),  # waking keeps the rest posture
                (bridge.stand_up, stand),
                (bridge.sit_down, sit),
                (bridge.rest, crouch),
            ]
            for verb, expected in steps:
                await verb()
                await asyncio.wait_for(
                    bridge.joints.wait_for(
                        lambda s, e=expected: s is not None and s.angles == e
                    ),
                    1.0,
                )

    asyncio.run(run())  # a pose that never shows up times out


def test_audio_input_streams_the_robot_microphone_to_several_subscribers():
    async def run() -> tuple[int, int, bool, bool]:
        async with NaoqiBridge(ALL_STREAMS) as bridge:
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
        with pytest.raises(NotRunningError, match="not running"):
            bridge.audio_input()
        return first, second, live, bridge.mic.latest() is None

    assert asyncio.run(run()) == (5, 5, True, True)
