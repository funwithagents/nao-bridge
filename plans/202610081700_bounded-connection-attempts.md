# Bounded connection attempts

**Status:** Done

Implements the edits to `specs/config.md` (`robot.connect_timeout_s`) and `specs/robot.md` (`QiNaoRobot.connect()` bounds each attempt), both `Updated`. Today one `session.connect()` to a host that doesn't answer waits for the OS TCP timeout (measured at ~76 s on macOS), so a wrong `robot.ip`, or a robot that's switched off, holds a server at startup for about 12.7 minutes with the default 10 tries.

libqi offers an async connect: `session.connect(url, _async=True)` returns a `qi.Future`; `future.wait(ms)` returns at the deadline with `FutureState.Running` while the host stays silent; `cancel()` then `close()` release the attempt at once. A refused port still finishes immediately with an error. This plan leaves the number of tries unchanged (10), so the worst case becomes `connect_tries × connect_timeout_s` = 50 s.

## Scope

- `src/nao_bridge/config.py` — `RobotSettings.connect_timeout_s: float = 5.0` (a positive, finite number; a known key in `from_dict`).
- `src/nao_bridge/robot.py`:
  - `QiNaoRobot(..., connect_timeout_s=5.0)`; `build_robot` passes it;
  - `connect()` connects asynchronously, waits up to the timeout, and on expiry cancels the future, closes that session, logs the attempt as timed out, and retries;
  - the final `RobotConnectionError` says how many attempts timed out or failed.
- `tests/test_robot.py` — the stub `qi` session returns a future: an attempt that never finishes is abandoned at the timeout and its session closed; refused attempts are retried as before; the timeout handed to `wait` is the config's, in ms.
- `tests/test_config.py` — the new field: default, loading, rejecting zero / negative / non-finite values.
- `examples/configs/*-real.json`, `README.md` (config reference), `specs/config.md`, `specs/robot.md`, `specs/_index.md`.

## Steps

1. Spec edits → `Updated`.
2. Config field and validation.
3. `QiNaoRobot.connect()`:
   ```python
   future = session.connect(url, _async=True)
   future.wait(int(self.connect_timeout_s * 1000))
   if not future.isFinished():   # silent host
       future.cancel(); session.close(); last_error = TimeoutError(...); continue
   if future.hasError():         # refused, unreachable network, …
       session.close(); last_error = RuntimeError(future.error()); continue
   ```
4. Tests, examples, README.
5. Measure on this machine: a `real` config with `connect_tries: 2` against an unreachable IP fails in about 2 × 5 s instead of about 2 × 76 s.
6. Specs → `Implemented`, this plan → `Done`; the analysis notes' C8 marked resolved.

## Verification

Done 2026-10-08:
- ruff and pyright are clean, and 104 tests pass. New tests:
  - an attempt that never finishes is waited on for exactly `connect_timeout_s`, then cancelled and its session closed;
  - when every attempt times out, the error says so and is chained to a `TimeoutError`;
  - every failed attempt's session is released;
  - `build_robot` passes the timeout through;
  - the config validates the new field.
- With real libqi against an unreachable IP and `connect_tries: 2`: attempt 1 timed out at 5 s, attempt 2 failed at once with "No route to host", 5.5 s in total (it was about 76 s per attempt).
- A refused local port still fails at once (0.44 s for 2 tries).

The original checklist:

ruff, pyright and pytest all clean. The measurement in step 5. A refused local port still fails at once.
