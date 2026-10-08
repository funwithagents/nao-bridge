"""Observable[T] (specs/observable.md): value, set vs update, latest-wins subscribers,
cancellation, wait_for, loop-thread only. Async runs via ``asyncio.run``."""

import asyncio
import threading

import pytest

from nao_bridge.observable import Observable


async def drain(
    changes_task_values: list[int], observable: Observable[int], n: int
) -> None:
    async for value in observable.changes():
        changes_task_values.append(value)
        if len(changes_task_values) == n:
            return


def test_value_reads_the_initial_then_the_latest():
    async def run() -> tuple[int, int, int]:
        observable = Observable(1)
        initial = observable.value
        observable.update(2)
        updated = observable.value
        observable.set(3)
        return initial, updated, observable.value

    assert asyncio.run(run()) == (1, 2, 3)


def test_set_wakes_subscribers_and_update_does_not():
    async def run() -> list[int]:
        observable = Observable(0)
        received: list[int] = []
        task = asyncio.create_task(drain(received, observable, 2))
        await asyncio.sleep(0)  # let the subscriber attach
        observable.set(1)
        await asyncio.sleep(0)
        observable.update(99)
        await asyncio.sleep(0)
        observable.set(2)
        await asyncio.wait_for(task, 1.0)
        return received

    assert asyncio.run(run()) == [1, 2]


def test_a_slow_subscriber_gets_the_latest_of_a_burst():
    async def run() -> list[int]:
        observable = Observable(0)
        received: list[int] = []
        task = asyncio.create_task(drain(received, observable, 1))
        await asyncio.sleep(0)
        for value in range(1, 6):
            observable.set(value)  # no await between: the subscriber can't keep up
        await asyncio.wait_for(task, 1.0)
        return received

    assert asyncio.run(run()) == [5]


def test_a_cancelled_subscriber_detaches():
    async def run() -> int:
        observable = Observable(0)
        task = asyncio.create_task(drain([], observable, 10))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        observable.set(1)  # no subscriber left to fail on
        return len(observable._subscribers)

    assert asyncio.run(run()) == 0


def test_wait_for_returns_at_once_or_on_the_first_match():
    async def run() -> tuple[int, int]:
        observable = Observable(4)
        immediate = await observable.wait_for(lambda v: v > 3)
        waiter = asyncio.create_task(observable.wait_for(lambda v: v >= 10))
        await asyncio.sleep(0)
        for value in (5, 10, 11):
            observable.set(value)
            await asyncio.sleep(0)
        return immediate, await asyncio.wait_for(waiter, 1.0)

    assert asyncio.run(run()) == (4, 10)


def test_set_off_the_event_loop_raises():
    observable = Observable(0)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            observable.set(1)
        except RuntimeError as e:
            errors.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert len(errors) == 1
    with pytest.raises(RuntimeError):
        observable.update(2)
