"""The fake backend (specs/robot.md): behavior runs, package list and sensor simulation.

Async runs via ``asyncio.run``.
"""

import threading
import time

from nao_bridge.fake_robot import FakeNaoRobot


def test_fake_behavior_runs_until_stopped():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("eagle-dance",))
    runner.start()
    while "eagle-dance" not in robot.running_behaviors:
        pass
    robot.stop_behavior("eagle-dance")
    runner.join(timeout=1.0)
    assert not runner.is_alive()
    assert robot.running_behaviors == []


def test_fake_motors_start_off_and_follow_wake_up_and_rest():
    robot = FakeNaoRobot()
    states = [robot.is_awake()]
    robot.wake_up()
    states.append(robot.is_awake())
    robot.rest()
    states.append(robot.is_awake())
    assert states == [False, True, False]
    assert [name for name, _ in robot.commands] == ["wake_up", "rest"]


def test_fake_close_ends_running_behaviors():
    robot = FakeNaoRobot()
    robot.behavior_duration_s = 5.0
    runner = threading.Thread(target=robot.run_behavior, args=("presentation",))
    runner.start()
    while not robot.running_behaviors:
        pass
    robot.close()
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
