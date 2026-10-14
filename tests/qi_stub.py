"""A stub ``qi`` module for the real and sim robots' tests (specs/robot.md): a
session whose connects can fail or go silent, and services that record their calls.
The ``stub_qi`` fixture (tests/conftest.py) installs it."""

import time
from typing import Any, ClassVar


class _StubSignal:
    """An ALMemory subscriber's ``signal``: records connects and disconnects."""

    def __init__(self, calls: list[tuple[str, str, tuple[Any, ...]]], key: str) -> None:
        self._calls = calls
        self._key = key

    def connect(self, handler: Any) -> int:
        self._calls.append(("ALMemory", "connect", (self._key,)))
        return 1

    def disconnect(self, link: int) -> None:
        self._calls.append(("ALMemory", "disconnect", (self._key,)))


class _StubSubscriber:
    def __init__(self, calls: list[tuple[str, str, tuple[Any, ...]]], key: str) -> None:
        self.signal = _StubSignal(calls, key)


class _StubService:
    def __init__(
        self, calls: list[tuple[str, str, tuple[Any, ...]]], name: str
    ) -> None:
        self._calls = calls
        self._name = name

    def __getattr__(self, method: str) -> Any:
        if method == "subscriber":
            return lambda key: _StubSubscriber(self._calls, key)

        def call(*args: Any) -> Any:
            self._calls.append((self._name, method, args))
            return True

        return call


class _StubFuture:
    """Stands in for the ``qi.Future`` of an async connect."""

    def __init__(self, finished: bool, error: str = "") -> None:
        self._finished = finished
        self._error = error
        self.waited_ms: int | None = None
        self.cancelled = False

    def wait(self, timeout_ms: int) -> None:
        self.waited_ms = timeout_ms
        if not self._finished:  # a silent host: the wait runs out
            time.sleep(timeout_ms / 1000)

    def isFinished(self) -> bool:
        return self._finished

    def hasError(self) -> bool:
        return bool(self._error)

    def error(self) -> str:
        return self._error

    def cancel(self) -> None:
        self.cancelled = True


class StubSession:
    """Stands in for ``qi.Session``: the first ``failures`` connects are refused and
    the next ``silent`` ones never answer; later ones connect."""

    failures: ClassVar[int] = 0
    silent: ClassVar[int] = 0
    connects: ClassVar[int] = 0
    closed: ClassVar[int] = 0
    futures: ClassVar[list[_StubFuture]] = []
    calls: ClassVar[list[tuple[str, str, tuple[Any, ...]]]] = []

    def connect(self, url: str, _async: bool = False) -> _StubFuture:
        assert _async, "connect must be asynchronous so a silent host can time out"
        cls = type(self)
        cls.connects += 1
        if cls.connects <= cls.failures:
            future = _StubFuture(finished=True, error=f"cannot reach {url}")
        elif cls.connects <= cls.failures + cls.silent:
            future = _StubFuture(finished=False)
        else:
            future = _StubFuture(finished=True)
        cls.futures.append(future)
        return future

    def service(self, name: str) -> _StubService:
        return _StubService(type(self).calls, name)

    def close(self) -> None:
        type(self).closed += 1

    def registerService(self, name: str, service: Any) -> int:
        type(self).calls.append(("session", "registerService", (name,)))
        return 7

    def unregisterService(self, service_id: int) -> None:
        type(self).calls.append(("session", "unregisterService", (service_id,)))
