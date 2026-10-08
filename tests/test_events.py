"""Event[T] (specs/events.md): ordered synchronous dispatch, snapshot iteration,
subscriber isolation."""

import pytest

from nao_bridge.events import Event


def test_handlers_receive_each_value_in_subscription_order():
    event: Event[int] = Event()
    received: list[tuple[str, int]] = []
    event.subscribe(lambda v: received.append(("a", v)))
    event.subscribe(lambda v: received.append(("b", v)))
    event.emit(1)
    event.emit(2)
    assert received == [("a", 1), ("b", 1), ("a", 2), ("b", 2)]


def test_no_replay_for_a_late_subscriber():
    event: Event[str] = Event()
    event.emit("early")
    received: list[str] = []
    event.subscribe(received.append)
    event.emit("late")
    assert received == ["late"]


def test_unsubscribe_stops_delivery_and_rejects_unknown_handlers():
    event: Event[int] = Event()
    received: list[int] = []
    event.subscribe(received.append)
    event.emit(1)
    event.unsubscribe(received.append)
    event.emit(2)
    assert received == [1]
    with pytest.raises(ValueError):
        event.unsubscribe(received.append)


def test_a_raising_handler_does_not_silence_the_others(
    caplog: pytest.LogCaptureFixture,
):
    event: Event[int] = Event()
    received: list[int] = []

    def broken(value: int) -> None:
        raise RuntimeError("boom")

    event.subscribe(broken)
    event.subscribe(received.append)
    event.emit(7)
    assert received == [7]
    assert "Event subscriber raised" in caplog.text


def test_subscription_changes_during_dispatch_apply_next_round():
    event: Event[int] = Event()
    received: list[str] = []

    def once(value: int) -> None:
        received.append(f"once:{value}")
        event.unsubscribe(once)
        event.subscribe(lambda v: received.append(f"added:{v}"))

    event.subscribe(once)
    event.emit(1)
    event.emit(2)
    assert received == ["once:1", "added:2"]
