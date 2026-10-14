# The sim robot and the session's sim

**Status:** In progress

Implements the changes to [robot.md](../specs/robot.md), [sim.md](../specs/sim.md) and [testing.md](../specs/testing.md) that give the `sim` backend a robot class of its own and the live tier one sim per session that tests can drive. It delivers three things:

- **One robot class per backend, named after it.** The Protocol becomes `NaoqiRobot` (was `AnyNaoqiRobot`). `RealNaoqiRobot`, in `real_robot.py`, is Naoqi over `qi` (was `NaoqiRobot`, in `naoqi_robot.py`). `SimNaoqiRobot(RealNaoqiRobot)`, in `sim_robot.py`, is the same robot at naoqi-sim's address, and holds the 2.8 Sit workaround that was `RealNaoqiRobot`'s `sit_through_crouch` flag. `FakeNaoqiRobot` is unchanged. The robots know nothing of the sim's lifecycle: the bridge keeps its lease.
- **The lease gives naoqi-sim's own object.** `SimLease.sim` is the `NaoqiSim` the lease started (`None` when borrowed), for naoqi-sim's API (the fake microphone, the devices to come), which only the process that started the sim has.
- **The live tier owns one sim per session.** `live_sim`, a session-scoped autouse fixture, calls `acquire_sim` with `spawn: "always"` at session start, on an event loop of its own thread, yields `lease.sim`, and releases the lease at session end. Each test's bridge borrows it (`spawn: "never"`). It replaces the lazy `RUN_SIM` with its owner bridge and the `pytest_sessionfinish` hook. A first test drives the sim: a 440 Hz tone played into its microphone comes out of `audio_input()`.

The bridge's default stays `spawn: "auto"`; only the live tier uses `always`. No wire protocol or config changes.

## Scope

- `src/naoqi_bridge/naoqi_robot.py` → `real_robot.py` (`git mv`): `RealNaoqiRobot`, without `sit_through_crouch`
- `src/naoqi_bridge/sim_robot.py` (new): `SimNaoqiRobot`
- `src/naoqi_bridge/robot.py`: the Protocol `NaoqiRobot`; `build_robot` returns a `SimNaoqiRobot` on `sim`
- `src/naoqi_bridge/sim.py`: `SimLease.sim`
- `src/naoqi_bridge/bridge.py`, `fake_robot.py`, `microphone.py`, the servers: the names
- `tests/qi_stub.py` (new): the stub `qi` module, out of `test_naoqi_robot.py`, its `stub_qi` fixture in `tests/conftest.py`; `tests/test_naoqi_robot.py` → `tests/test_real_robot.py`; `tests/test_sim_robot.py` (new): the sim robot's address and the Sit tests; `tests/test_robot.py`: `build_robot` on sim
- `tests-e2e/conftest.py`: `live_sim`; `tests-e2e/support.py`: `session_sim()`, `RUN_SIM` gone; `tests-e2e/test_live_sim.py`; `tests-e2e/test_live_streams.py`: the tone test
- Specs: robot.md, sim.md, testing.md (`Updated` until this plan is `Done`), `_overview.md` (diagram, table), `_index.md`, frontmatter; `AGENTS.md` (project map)

## Steps

1. **Rename**, word-bounded, in this order, across tracked files except `Done` plans and their index rows: `NaoqiRobot` → `RealNaoqiRobot`, `AnyNaoqiRobot` → `NaoqiRobot`, `naoqi_robot` → `real_robot`, with `git mv` for the module and its test.
2. **`SimNaoqiRobot`** takes the Sit workaround; `build_robot` builds it on `sim`, `sit_through_crouch` on 2.8.
3. **`SimLease.sim`**, read-only.
4. **The fast tier**: the stub `qi` shared through `tests/qi_stub.py`; the Sit tests on `SimNaoqiRobot`; `build_robot` on sim returns a `SimNaoqiRobot` at naoqi-sim's address.
5. **The live tier**: `session_sim()` and `live_sim`. A sim that can't start (a naoqi-sim already running included) skips the session, or fails it when `NAOQI_E2E_TARGET` is set, as before. The tone test skips on `real`.
6. **Verification through PR #6's CI only**: this machine's sim serves another session.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` clean; `uv run pytest tests-e2e` with `NAOQI_E2E_TARGET=real` and no robot only skips (no Docker touched).
- `git grep -n -P '\bAnyNaoqiRobot\b|naoqi_robot|RUN_SIM' -- ':!plans/2*'` returns nothing.
- Both `e2e-sim` entries green on PR #6, the tone test passing on both.

Mark this plan `Done` here and in [_index.md](_index.md), and the three specs `Implemented`, once all pass.
