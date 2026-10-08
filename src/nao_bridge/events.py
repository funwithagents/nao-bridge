"""A minimal, generic publish/subscribe primitive: ``Event[T]`` (specs/events.md).

Standard library only. An ``Event[T]`` holds a list of handlers; ``subscribe`` /
``unsubscribe`` manage them and ``emit`` calls each one inline, in subscription order,
with the published value. It is synchronous and stores nothing beyond its handlers.
"""

import logging
from collections.abc import Callable

__all__ = ["Event"]

_logger = logging.getLogger(__name__)


class Event[T]:
    """A synchronous, generic pub/sub signal carrying one value of type ``T``.

    ``emit`` iterates a snapshot of the handler list, so a handler may subscribe or
    unsubscribe (itself or another) during dispatch; the change applies next round.
    """

    def __init__(self) -> None:
        self._handlers: list[Callable[[T], None]] = []

    def subscribe(self, handler: Callable[[T], None]) -> None:
        """Register ``handler`` to be called on every future :meth:`emit`."""
        self._handlers.append(handler)

    def unsubscribe(self, handler: Callable[[T], None]) -> None:
        """Remove a subscribed ``handler``; ``ValueError`` if it never subscribed."""
        self._handlers.remove(handler)

    def emit(self, value: T) -> None:
        """Call every handler with ``value``, in subscription order.

        A handler that raises is logged and skipped: dispatch continues to the others,
        and ``emit`` itself never propagates a handler's exception.
        """
        for handler in list(self._handlers):
            try:
                handler(value)
            except Exception:
                _logger.exception(
                    "Event subscriber raised; continuing to next subscriber"
                )
