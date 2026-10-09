"""The fake backend (specs/robot.md): behavior runs, timed speech and postures, the
joints of its posture, package list and sensor simulation.

Async runs via ``asyncio.run``.
"""

import threading
import time
from collections.abc import Callable

import pytest

from nao_bridge.fake_robot import JOINT_NAMES, POSTURE_ANGLES, FakeNaoRobot


def test_fake_behavior_runs_until_stopped():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("eagle-dance",))
    runner.start()
    while "eagle-dance" not in robot.running_behaviors:
        pass
    robot.stop_behavior("eagle-dance")
    assert robot.running_behaviors == []  # at once, not when the run's thread wakes
    runner.join(timeout=1.0)
    assert not runner.is_alive()


def run_in_thread(
    call: Callable[[], object], started: Callable[[], bool]
) -> threading.Thread:
    runner = threading.Thread(target=call)
    runner.start()
    while not started():
        pass
    return runner


def test_fake_speech_lasts_until_stopped_or_closed():
    robot = FakeNaoRobot()
    robot.speech_duration_s = 5.0
    runner = run_in_thread(lambda: robot.say("Hello"), lambda: robot.speaking)
    robot.stop_speech()
    assert not robot.speaking  # at once, not when the say's thread wakes
    runner.join(timeout=1.0)
    runner = run_in_thread(lambda: robot.say("Again"), lambda: robot.speaking)
    robot.close()
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert not robot.speaking


def test_fake_posture_move_lasts_until_stopped_and_still_reports_its_outcome():
    robot = FakeNaoRobot()
    robot.posture_duration_s = 5.0
    robot.posture_succeeds = False
    outcome: list[bool] = []
    runner = run_in_thread(
        lambda: outcome.append(robot.go_to_posture("Stand", 0.8, 3)),
        lambda: robot.moving_posture,
    )
    robot.stop_posture()
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert outcome == [False]
    assert [name for name, _ in robot.commands] == ["go_to_posture", "stop_posture"]


def test_fake_stop_before_the_call_finds_nothing_to_stop():
    robot = FakeNaoRobot()
    robot.speech_duration_s = 0.2
    robot.stop_speech()  # as on the robot: a stop ahead of the call is lost
    started = time.monotonic()
    robot.say("Hello")
    assert time.monotonic() - started >= 0.15


@pytest.mark.fake_behavior_durations
def test_fake_durations_default_to_robot_like_times():
    robot = FakeNaoRobot()
    assert (
        robot.behavior_duration_s,
        robot.speech_duration_s,
        robot.posture_duration_s,
    ) == (5.0, 1.0, 2.0)


def test_fake_motors_start_off_and_follow_wake_up_and_rest():
    robot = FakeNaoRobot()
    states = [robot.is_awake()]
    robot.wake_up()
    states.append(robot.is_awake())
    robot.rest()
    states.append(robot.is_awake())
    assert states == [False, True, False]
    assert [name for name, _ in robot.commands] == ["wake_up", "rest"]


def test_fake_joints_follow_its_posture_and_wake_up_keeps_it():
    robot = FakeNaoRobot()

    def angles() -> tuple[float, ...]:
        names, values = robot.get_joints()
        assert tuple(names) == JOINT_NAMES
        return tuple(values)

    poses = [angles()]
    robot.wake_up()
    poses.append(angles())
    robot.go_to_posture("Stand", 0.8, 3)
    poses.append(angles())
    robot.go_to_posture("Sit", 0.8, 3)
    poses.append(angles())
    robot.rest()
    poses.append(angles())
    crouch, stand, sit = (POSTURE_ANGLES[p] for p in ("Crouch", "Stand", "Sit"))
    assert poses == [crouch, crouch, stand, sit, crouch]
    assert len({crouch, stand, sit}) == 3


def test_fake_posture_is_kept_by_a_failed_stopped_or_unknown_move():
    robot = FakeNaoRobot()
    robot.posture_succeeds = False
    robot.go_to_posture("Stand", 0.8, 3)
    failed = robot.posture
    robot.posture_succeeds = True
    robot.go_to_posture(
        "LyingBack", 0.8, 3
    )  # a Naoqi posture the fake has no angles for
    unknown = robot.posture
    robot.posture_duration_s = 5.0
    runner = run_in_thread(
        lambda: robot.go_to_posture("Stand", 0.8, 3), lambda: robot.moving_posture
    )
    robot.stop_posture()
    runner.join(timeout=1.0)
    assert (failed, unknown, robot.posture) == ("Crouch", "Crouch", "Crouch")


def test_fake_close_ends_running_behaviors():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("presentation",))
    runner.start()
    while not robot.running_behaviors:
        pass
    robot.close()
    assert robot.running_behaviors == []  # at once, not when the run's thread wakes
    runner.join(timeout=1.0)
    assert not runner.is_alive()


def test_fake_sensor_events_reach_only_a_subscribed_callback():
    robot = FakeNaoRobot()
    touches: list[tuple[str, float]] = []
    robot.touch("FrontTactilTouched", 1.0)  # nobody subscribed yet: dropped
    robot.subscribe_touch(lambda key, value: touches.append((key, value)))
    robot.touch("RearTactilTouched", 1.0)
    robot.unsubscribe_touch()
    robot.touch("MiddleTactilTouched", 0.0)
    assert touches == [("RearTactilTouched", 1.0)]


def test_fake_package_list_is_a_fresh_copy():
    robot = FakeNaoRobot()
    robot.list_packages()[0]["uuid"] = "tampered"
    assert robot.list_packages()[0]["uuid"] != "tampered"


def test_fake_pushes_paced_silence_while_audio_is_subscribed():
    robot = FakeNaoRobot()
    robot.audio_chunk_s = 0.01
    chunks: list[tuple[int, int, bytes]] = []
    robot.subscribe_audio(lambda *chunk: chunks.append(chunk), "front")
    time.sleep(0.2)
    robot.unsubscribe_audio()
    count = len(chunks)
    time.sleep(0.05)
    assert len(chunks) == count  # nothing pushed after unsubscribing
    assert 5 <= count <= 25  # about one per 10 ms
    assert chunks[0] == (1, 160, bytes(320))


def test_fake_audio_push_can_be_paused_for_injected_chunks():
    robot = FakeNaoRobot()
    robot.audio_chunk_s = None
    chunks: list[bytes] = []
    robot.subscribe_audio(lambda _c, _s, buffer: chunks.append(buffer), "front")
    robot.emit_audio(1, 1, b"\x01\x00")
    time.sleep(0.05)
    robot.close()
    assert chunks == [b"\x01\x00"]
