# Cancellable verbs

**Status:** Done

Implements `specs/bridge.md` ("Cancellation", and the lifecycle lines that point to it), the `stop_posture` Protocol method and the timed fake speech and postures in `specs/robot.md`, and the extended instant-fake fixture in `specs/testing.md`. When it's done, cancelling a spanning verb (`say`, `stand_up` / `sit_down`, `run_behavior`, the four catalog verbs) stops its effect on the robot before the `CancelledError` propagates, and the tracking stays honest until then. Cancelling `start()` or `stop()` leaves nothing half up. Left out (the spec's open questions): an interruptible `connect()`, "newest `say` wins", and the live check that `stopAll` also stops animated speech's gestures. The servers' code doesn't change.

## Scope

- `src/nao_bridge/robot.py` — `stop_posture()` on the `NaoRobot` Protocol.
- `src/nao_bridge/real_robot.py` — `stop_posture()` → `ALRobotPosture.stopMove()`.
- `src/nao_bridge/fake_robot.py` — `say` / `go_to_posture` block for `speech_duration_s` / `posture_duration_s` (class defaults `DEFAULT_SPEECH_DURATION_S = 1.0`, `DEFAULT_POSTURE_DURATION_S = 2.0`), ended early by `stop_speech()` / `stop_posture()` / `close()`; `speaking` / `moving_posture` reads; `stop_posture` recorded.
- `src/nao_bridge/bridge.py` — a `_span` helper for spanning verbs (stop on cancel, re-send, owned); `say`, `_go_to_posture`, `_run_behavior` / `_play` on it; tracking cleared after the stop; `start()` tears down on a cancel during `connect`; `stop()` owned.
- `tests/conftest.py` — the autouse fixture also zeroes the two new defaults.
- `pyproject.toml` — the `fake_behavior_durations` marker description names all three durations.
- `tests/test_bridge.py` — cancellation tests (below).
- `tests/test_fake_robot.py` — timed, stoppable speech and postures.
- `tests/test_real_robot.py` — `stop_posture` maps to `ALRobotPosture.stopMove` on the stub `qi`.
- `README.md` — a short "Cancelling a verb" note, if the README documents the verbs' behavior (check).
- Status lines and index rows: `specs/bridge.md`, `specs/robot.md`, `specs/testing.md` → `Implemented`; this plan → `Done`; the `_overview.md` status paragraph and bridge row back to "every spec Implemented".

## Steps

1. **Seam.** Add `def stop_posture(self) -> None: ...` to `NaoRobot`. Implement it in `RealNaoRobot` (`self._service("ALRobotPosture").stopMove()`). pyright then flags the fake until step 2.
2. **Fake timing.** In `FakeNaoRobot`, generalize the behavior-run mechanism into a private "timed call" helper: register a `threading.Event` under the lock, record the command, `wait(duration)`, deregister in `finally`. Keep the semantics that "a stop that arrives before the call registered finds nothing" (the race the bridge's re-send covers). `say` uses it with `speech_duration_s` and a single speech slot; `go_to_posture` uses it with `posture_duration_s` and a single posture slot, returning `posture_succeeds` afterwards. `stop_speech` / `stop_posture` record and set the slot's event, if any; `close()` sets every pending event, as it does for behaviors. Add the `speaking` / `moving_posture` properties. Update the class docstring.
3. **Fast-tier fixture.** In `tests/conftest.py`, monkeypatch `DEFAULT_SPEECH_DURATION_S` and `DEFAULT_POSTURE_DURATION_S` to `0.0` next to the behavior default, under the same marker check. Update the marker text in `pyproject.toml`. Check the subprocess server tests: if any of them call `say` / `stand_up`, accept the 1–2 s or have them avoid it.
4. **`_span` in the bridge.** Add module constants `STOP_RETRY_S = 0.5`, `STOP_ATTEMPTS = 4`. Add
   `async def _span[T](self, verb: str, call: Callable[[NaoRobot], T], stop: Callable[[NaoRobot], None]) -> T`:
   - `robot = self.robot`; `fut = asyncio.ensure_future(asyncio.to_thread(call, robot))`.
   - `try: return await asyncio.shield(fut)`, mapping an `Exception` to `CommandFailedError` as `_act` does.
   - `except asyncio.CancelledError:` run `self._stop_span(verb, robot, fut, stop)` as an **owned** step, then `raise`.
   - `_stop_span`: up to `STOP_ATTEMPTS` times, `await asyncio.to_thread(stop, robot)` (an `Exception` there → `logger.warning`, return), then `await asyncio.wait({fut}, timeout=STOP_RETRY_S)`; return once `fut.done()`. After the last attempt, `logger.warning("%s: the robot did not confirm the stop", verb)`. Retrieve `fut`'s exception if done, so nothing logs "exception never retrieved", and drop it.
   - The owned helper: `task = asyncio.ensure_future(coro)`; loop `await asyncio.shield(task)`, catching `CancelledError` and remembering it, until `task.done()`; then re-raise the remembered cancel (the caller re-raises the original anyway). Reuse it for `stop()` in step 6.
   - `shield` around `fut` is what lets the cancel be caught while the thread's result is still awaited. A cancel before `ensure_future` (during the motors check) never enters `_span`, so it propagates with nothing sent, as the spec says.
5. **Wire the spanning verbs.**
   - `say`: `await self._span("say", lambda r: r.say(text), lambda r: r.stop_speech())`.
   - `_go_to_posture`: `_span` with `go_to_posture(...)` and `stop_posture()`. The `reached` check stays and only runs on a normal return.
   - `_run_behavior`: `_span` with `run_behavior(name)` and `stop_behavior(name)`. Tracking (`_running_behaviors`, and `_running` in `_play`) is still removed in `finally`. Since `_span` returns or raises only after the stop is confirmed (or given up), the `finally` now runs after the stop. That's the spec's "cleared only once the behavior has stopped". Check the concurrency: a `stop_dance` arriving during `_stop_span` still finds the item tracked and sends a harmless second `stop_behavior`.
   - `expressive_reaction` goes through `_play`, so it stops the behavior it picked.
   - Instant verbs stay on `_act`.
6. **Lifecycle.** `start()`: move `await asyncio.to_thread(robot.connect)` into a shape where a `CancelledError` during it lets the connect thread finish (`shield` + await the future to completion, as in `_span`, without a stop), then `_teardown(robot)` and re-raise. The existing `except BaseException` already covers the later steps. `stop()`: run its body (joints task, `_teardown`, tracking clear) through the owned helper, so a cancel arriving mid-teardown is absorbed until every step has run.
7. **Docs.** Docstrings on `say`, `stand_up`, `sit_down`, `run_behavior` and the catalog verbs: "cancelling stops it". README note if it applies. Flip the statuses (see Scope).

## Verification

New tests in `tests/test_bridge.py`, on the fake, with the relevant duration set to 5 s:

- **cancelled `dance` stops the behavior:** start `dance` as a task, wait until `current_dances` shows it, cancel, `await` → `CancelledError`. Then: `fake.running_behaviors` is empty, a `stop_behavior` for it was recorded, `current_dances` is empty, and the cancel took well under the 5 s duration. The same test runs over `body_action`, `run_app`, `run_behavior` and `expressive_reaction` (which stops the picked behavior, from `current_expressive_reactions`).
- **tracking holds until the stop:** with a fake subclass whose `stop_behavior` sleeps briefly before stopping, `current_dances` still lists the item while the cancelled task is stopping, and is empty after.
- **cancelled `say` / `stand_up` stop the robot:** `fake.speaking` / `fake.moving_posture` go false, and `stop_speech` / `stop_posture` were recorded. The `stand_up` caller gets `CancelledError`, not `CommandFailedError`, even with `posture_succeeds = False`.
- **stop re-sent when the first one misses:** a fake subclass ignores the first `stop_behavior`. The cancel still ends the behavior, and two `stop_behavior` commands were recorded.
- **give-up is bounded:** a fake whose `stop_behavior` never stops anything. The cancel returns within about `STOP_ATTEMPTS × STOP_RETRY_S`, a warning is logged (`caplog`), and the tracking is cleared. Monkeypatch `STOP_RETRY_S` down to keep the test fast.
- **a failing stop:** `stop_behavior` raises. The caller gets `CancelledError`, a warning is logged.
- **a second cancel doesn't cut the stop short:** cancel twice in a row; the behavior has still stopped when the task ends.
- **cancel before the command:** with a fake whose `is_awake` blocks, cancelling `dance` during the motors check records no `run_behavior` and no `stop_behavior`.
- **session usable after a cancel:** a second `dance` right after a cancelled one runs and is tracked; the motors are still on (no `rest` recorded).
- **instant verb cancel:** cancelling `change_eyes_color` returns promptly; the command was recorded once.
- **`start()` cancelled during connect:** with a fake whose `connect` blocks briefly, cancel `start()`. `CancelledError`, `running` is false, `close` was recorded after `connect`.
- **`stop()` cancelled mid-teardown:** with a slow `unsubscribe_touch`, cancel `stop()`. `close` was still recorded, and the bridge is not running.

`tests/test_fake_robot.py`: a `say` / `go_to_posture` with a 5 s duration ends early on `stop_speech` / `stop_posture` and on `close()`; `posture_succeeds` is still returned; with defaults (marker), the durations are 1 s and 2 s.

`tests/test_real_robot.py`: `stop_posture()` calls `ALRobotPosture.stopMove` on the stub `qi`.

Existing tests (MCP `test_leaving_serve_cancels_the_behaviors_still_running`, the WebSocket ones) must pass unchanged. The MCP one now also sees `stop_behavior` recorded, which is worth asserting.

Then `uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest`. On a real Nao (`NAO_IP`), worth one manual check of the third open question: cancel a `say` mid-sentence and watch whether the gestures stop. Mark this plan `Done` (here and in [_index.md](_index.md)) and flip the three specs to `Implemented` only once all pass.
