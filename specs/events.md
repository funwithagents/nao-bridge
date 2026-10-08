---
code:
  - src/nao_bridge/events.py
tests:
  - tests/test_events.py
---

# Event (pub/sub primitive)

**Status:** Implemented

## Purpose

`Event[T]` in `events.py` is a tiny, generic publish/subscribe primitive. One producer *publishes* a value and any number of consumers *subscribe* to receive it, without knowing about each other. The bridge uses it for discrete occurrences where every one matters and nothing needs replaying, starting with `bridge.on_touch` ([bridge.md](bridge.md)).

It depends on nothing but the standard library and knows nothing about Nao, the bridge or its payloads. Who uses it, and what flows through it, is up to the consumer.

## Decided

### The type: `Event[T]`

| Method | Role |
|---|---|
| `subscribe(handler: Callable[[T], None])` | Register `handler` to be called on every future `emit`. |
| `unsubscribe(handler)` | Remove a previously subscribed `handler` (raises `ValueError` if it was never subscribed). |
| `emit(value: T)` | Call every subscribed handler with `value`, **in subscription order**. |

- **Generic over the payload.** pyright checks the payload type end to end: `Event[TouchEvent]` delivers `TouchEvent`s. `Event[None]` is a pure "it happened" signal.
- **One value per `emit`.** A signal that carries several things carries them as one composite value (a dataclass), so `T` names exactly what a handler receives.

### Semantics

- **Synchronous, inline dispatch.** `emit` calls each handler directly, in subscription order, and returns once they have all run. There is no queue and no thread: the caller's thread runs the handlers. Crossing threads is the producer's job. The bridge emits on its event loop, so handlers run there and may schedule tasks.
- **Snapshot iteration.** `emit` iterates a copy of the handler list. A handler may subscribe or unsubscribe during dispatch, and the change takes effect from the next `emit`.
- **Stateless beyond its handlers.** No replay: a subscriber only sees `emit`s that happen after it subscribed.
- **Subscriber isolation.** A handler that raises is caught and logged (`logging.getLogger(__name__)`), and dispatch continues to the remaining handlers. One faulty consumer can neither abort an `emit` nor silence the others.

### Why its own module

A standalone `events.py` with zero project imports is a dependency leaf. A producer can own `Event[...]` outputs while depending only on this primitive.

## Open questions

1. **Error aggregation.** Handler errors are logged, not returned to the `emit` caller. Deferred until a consumer needs failures programmatically.
2. **Async handlers.** Only synchronous handlers today; a handler that needs to `await` schedules a task. An async variant would be a separate addition.
