---
code:
  - src/nao_bridge/observable.py
tests:
  - tests/test_observable.py
---

# Observable (`observable.py`)

**Status:** Implemented

## Purpose

`Observable[T]` is a value a caller can read directly and also subscribe to: `value` for the current state, `changes()` to be woken when a new value is published. The bridge uses it for **states**, where the latest value is what matters and an intermediate one can be skipped, starting with `bridge.joints` ([bridge.md](bridge.md)).

It fills the gap between the bridge's other two shapes. A read-only property has to be polled. A stream (like `audio_input()`, [microphone.md](microphone.md)) delivers every item, so a slow consumer falls behind. A pose should be readable at any moment *and* push its updates, without polling and without a backlog.

## Core concepts / Decided

### The surface

```python
class Observable[T]:
    def __init__(self, initial: T) -> None: ...
    @property
    def value(self) -> T: ...                              # the current value; no await
    def changes(self) -> AsyncIterator[T]: ...             # yields each *published* value from now on
    async def wait_for(self, predicate: Callable[[T], bool]) -> T: ...  # the current value if it
                                                           # matches, else the first published one that does
    def set(self, value: T) -> None: ...                   # replace and publish
    def update(self, value: T) -> None: ...                # replace silently (no wake-up)
```

### Semantics

- **Read any time, subscribe from the event loop.** `value` is a plain attribute read, from any thread.
- **`changes()` is an async iterator.** Each subscriber gets its own one-slot queue, created when the iterator is first driven and removed when it closes. So a subscriber only sees values published after it subscribed.
- **Latest wins.** A subscriber that falls behind gets the latest value, not every intermediate one: the value is a state, not a log. Nothing ever blocks the producer.
- **Cancellation.** Cancelling the task blocked in `async for` ends the iteration and detaches that subscriber. The others keep being served.
- **Producers publish on the loop.** `set` and `update` must be called on the event-loop thread; elsewhere they raise `RuntimeError` because there's no running loop. A producer on another thread goes through `loop.call_soon_threadsafe`.
- **The owner decides what counts as a change.** It's not decided by equality: `update` replaces the value for readers, and `set` also wakes subscribers. The joints task `set`s every sample, since a new pose sample is the change ([bridge.md](bridge.md)).
- **`wait_for`** returns `value` at once if the predicate already holds, otherwise the first published value that does.
- **Lifetime.** An observable belongs to the object that exposes it (`bridge.joints` belongs to the bridge) and outlives that object's sessions. A caller can keep iterating across sessions; a published `None` tells it the state reset.

### Testable without a robot

It's pure asyncio, so `tests/` pin it directly:
- reading the initial and latest value;
- `set` wakes subscribers and `update` doesn't;
- a subscriber that keeps up receives every published value, and one that doesn't gets the latest of a burst;
- a cancelled subscriber detaches, and later publications still work;
- `wait_for`, both when the predicate already holds and when it doesn't;
- `set` from a plain thread raises.

## Open questions

1. **Thread-safe producers.** The class could offer `set_threadsafe(loop, value)` itself instead of leaving `call_soon_threadsafe` to the producer. Deferred until a producer on another thread exists; the joints task runs on the loop.
