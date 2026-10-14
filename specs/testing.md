---
code:
  - tests/conftest.py
  - tests/qi_stub.py
  - pyproject.toml
  - tests-e2e/conftest.py
  - tests-e2e/support.py
tests:
---

# Testing

**Status:** Implemented

## Purpose

naoqi-bridge's testing strategy — the two-tier structure and what a good test looks like. It's a **cross-cutting practice**, not a runtime concept: nothing here ships in the library. It exists as a spec so the decisions have one honest home that stays in sync with the setup, rather than living half in [project.md](project.md) (the tooling choices) and half in [AGENTS.md](../AGENTS.md) (the operational how-to). The concrete shell commands to run each tier live in [AGENTS.md](../AGENTS.md) "Testing".

## Two tiers, physically separated

Tests split into two directories, and the split is structural — a directory boundary, not a marker or an opt-out flag:

| Tier | Directory | Network | Deterministic | Runs by default |
|---|---|---|---|---|
| Unit / integration | `tests/` | never | yes | **yes** |
| Live / e2e | `tests-e2e/` | real service | no | **no** |

- **`tests/` is the normal dev loop.** Fast, deterministic, no real network, no credentials. `pyproject.toml`'s `testpaths = ["tests"]` points the default `uv run pytest` here, so this is what runs on every change and what any contributor or CI can run with zero credentials.
- **`tests-e2e/` is opt-in.** It calls a real external service — network, credentials, non-deterministic output — so it is deliberately *not* collected by the default run. Because `testpaths` already excludes it, no pytest marker or `--run-e2e` flag is needed: the physical separation is the whole mechanism. Run it explicitly (`uv run pytest tests-e2e`).

The `tests/` tier mirrors the `src/naoqi_bridge/` module layout (`test_<module>.py`, plus the `test_project_map.py` drift-guard); `tests-e2e/` is organized around live scenarios rather than modules.

## What a good test asserts

- **Functional, not tautological.** Exercise what a feature actually does — inputs → outputs, state changes, side effects — not that it runs or matches its own signature. A test that would pass against a broken implementation (asserting a constant, that an object isn't `None`, that a mock was called) isn't worth writing.
- **Drive the public API like a real caller.** Prefer exercising the public surface the way a consumer would over reaching into internals; assert on the observable result.
- **In the e2e tier, assert on behavior, not exact output.** Real service responses vary run to run, so a live test asserts a robust property ("a non-empty result came back", "the side effect happened"), never a specific string.

## Instant fake behaviors

The fake's behaviors last `FakeNaoqiRobot.DEFAULT_BEHAVIOR_DURATION_S` (5 s), its speech `DEFAULT_SPEECH_DURATION_S` (1 s) and its posture moves `DEFAULT_POSTURE_DURATION_S` (2 s). That way demos and client development see them running and stoppable ([robot.md](robot.md)). In the fast tier it would make every dance, `say` or `stand_up` wait, so an autouse fixture in `tests/conftest.py` sets all three class defaults to `0.0` for every test.
- A test that needs one in flight (a running behavior, a `say` or posture move to cancel) sets `behavior_duration_s`, `speech_duration_s` or `posture_duration_s` on its fake instance (reached through `bridge.robot`).
- A test that checks the real defaults is marked `@pytest.mark.fake_behavior_durations`, which the fixture leaves alone.
- Tests that start a server in a subprocess don't get the fixture, so they don't run behaviors, speech or postures.

## Test isolation

The package holds no process-global or singleton state, so neither tier has a reset fixture today. If one appears, both tiers carry an identical autouse fixture (in each tier's `conftest.py`) that resets it before and after every test, duplicated rather than shared because `tests-e2e/` isn't a package that imports from `tests/`. The fast tier's one autouse fixture, the instant fake behaviors above, is deliberately not mirrored: the live tier has no fake.

## Live tier: skip without credentials

A live test needs real credentials, and it must **skip — never fail** — when they're absent, so you exercise only the services you hold keys for and a contributor (or CI) with none is never broken. `tests-e2e/support.require_env(NAME)` implements this: it returns the env var or calls `pytest.skip(...)` when it's unset. Credentials come from the environment, never committed. The one exception is a target asked for by name: `NAOQI_E2E_TARGET=sim` turns a sim that can't run into a failure (below), since whoever set it expects the tests to run.

For naoqi-bridge the live service is a Naoqi: a **simulated Nao** by default, or a **real Nao robot** (below, "Live tier: the target"). Either way the tier needs the `qi` wheel installed. The fast tier never needs a robot — it runs `NaoqiBridge` and both servers on the `fake` backend (`FakeNaoqiRobot`, reached through `bridge.robot`), and checks `RealNaoqiRobot`'s connection rules against a stub `qi` module.

## Live tier: the target

The live tier runs against one target per run, chosen by the environment:

| Variable | Values | Meaning |
|---|---|---|
| `NAOQI_E2E_TARGET` | `sim` (when unset), `real` | The backend the tests' bridges use; the words are the config's backends |
| `NAOQI_E2E_SIM_VERSION` | `2.1` (when unset), `2.8` | `sim`: the NAOqi version of the sim |
| `NAOQI_E2E_SIM_VIEWER` | a flag (`1`, `true`, `yes`) | `sim`: the sim window instead of a headless sim, to watch the run |
| `NAOQI_E2E_VIEWER` | a flag (`1`, `true`, `yes`) | Either target: run the viewer test, which opens the bridge's viewer window ([viewer.md](viewer.md), "Testing"); needs a display, so never in CI |
| `NAOQI_E2E_IP`, `NAOQI_E2E_PORT` | an address, a port (9559 when unset) | `real`: the robot |

An unknown target or version fails the session at collection (`pytest.UsageError`).

**The `sim` target** ([sim.md](sim.md)). One sim serves the whole session, one bridge each test:
- **The session's sim.** `live_sim`, a session-scoped autouse fixture in `tests-e2e/conftest.py`, calls `acquire_sim` (the function the bridge itself uses) with `spawn: "always"` at session start, on an event loop of its own thread that both the start and the stop run on, and releases the lease at session end, which stops the sim. `always`, not the bridge's default `auto`: the session must own its sim, since naoqi-sim's own API (`NaoqiSim.fake_audio`, the devices to come) lives in the process that started it, and it must never drive a sim someone else runs. A naoqi-sim already running on the machine is therefore a sim that can't run (below), named in the message.
- **`live_sim` yields that `NaoqiSim`** (`None` on the `real` target): a test that drives the sim itself takes it, as the audio test that plays a 440 Hz tone into its microphone and hears it through `audio_input()`.
- **Each test's bridge** (and each server a test starts, in a subprocess or not) uses `backend: "sim"` with `spawn: "never"`: it borrows the session's sim, never starts a second one, and fails clearly if it's gone. A bridge costs one qi connection, so each test gets its own, with the streams it asks for. The fixture's sim runs headless with the render camera and the placeholder robot model, a silent audio output and naoqi-sim's fake audio input, so the audio stream carries what NAOqi really pushes (naoqi-sim's own CI settings); `NAOQI_E2E_SIM_VIEWER=1` opens the window instead (`sim.config.viewer.headless: false`), with the robot model the machine has. The images are never built by the tier: `uv run naoqi-sim fetch-and-build-images` once per machine.

**When the sim can't run** (no `[sim]` extra, no Docker, images missing or outdated, a port taken, a naoqi-sim already running on the machine), what happens depends on whether the target was asked for:
- `NAOQI_E2E_TARGET` unset: every test **skips**, with naoqi-sim's message saying what's missing, so a contributor without Docker is never broken;
- `NAOQI_E2E_TARGET=sim` set: the run **fails**. CI sets it ([ci.md](ci.md)), where a skip would turn the job green with nothing tested.

**The `real` target** is a Nao at `NAOQI_E2E_IP`. Without the variable, the tests skip, as without credentials.

The tier runs serially (pytest's default here): one sim per machine, one robot.

## Live tier: levels of risk

A live test that moves the robot needs more than its address: someone has to have cleared the floor. So the live tier has three levels, each an opt-in on top of the one before, and a test skips unless its level is switched on:

| Level | Switched on by | What it may do | Modules |
|---|---|---|---|
| **Safe** | the target | Anything that doesn't move the limbs: connect, catalog, eyes, TTS language, speech, basic awareness (motors off), errors, the joints and audio streams, cancelling a `say` | `test_live_robot.py`, `test_live_verbs.py`, `test_live_streams.py`, the safe half of `test_live_cancellation.py`, the MCP half of `test_live_servers.py` |
| **Motion** | `NAOQI_E2E_ALLOW_MOTION=1`; always on with the `sim` target | Motors on, postures, breathing, body actions, reactions, a dance, and cancelling them; the WebSocket server, whose connect ritual wakes the robot | `test_live_motion.py`, the motion half of `test_live_cancellation.py`, the WebSocket half of `test_live_servers.py` |
| **Interactive** | `NAOQI_E2E_INTERACTIVE=1`; skipped with the `sim` target (naoqi-sim has no touch input yet, [sim.md](sim.md)) | Asks the person at the robot to act (touch the head) and waits for it | the touch test in `test_live_streams.py` |

A flag is on when it's `1`, `true` or `yes`. `tests-e2e/support.py` holds what the levels share:
- `require_env(name)` and `require_flag(name)`, which skip when the variable or the flag is missing;
- `live_config(...)`, the target's `NaoqiBridgeConfig` with the streams a test asks for: `sim` with `spawn: "never"` and the run's version, or `real` at `NAOQI_E2E_IP` / `NAOQI_E2E_PORT`;
- `live_session(...)`, which runs a bridge on it and leaves the robot as it found it: eyes white and, at the motion level, `rest`;
- the catalog pickers, which take ids from the robot's own catalog (installed dances and apps differ per robot) and skip when it has none (always, on a sim, for dances, apps and body actions: [sim.md](sim.md), "What a sim offers the bridge").

Each test runs its own session under `asyncio.run`, since a bridge's streams belong to the loop that started it. A test about the robot itself (whether a behavior is still running) may ask Naoqi directly through `bridge.robot`.

Live tests also **measure**. Each cancellation test records how long its cancel took to return, and the audio test records the chunk size Naoqi really pushes ([microphone.md](microphone.md) open question). `tests-e2e/conftest.py` prints these measurements in the run's terminal summary, so the stop retry interval ([bridge.md](bridge.md) "How a spanning verb stops") can be tuned on real numbers. `uv run pytest tests-e2e` runs every level a headless 2.1 sim allows; `NAOQI_E2E_SIM_VERSION=2.8` the same on 2.8, `NAOQI_E2E_SIM_VIEWER=1` with the window. On a robot, run the safe level alone with `NAOQI_E2E_TARGET=real NAOQI_E2E_IP=… uv run pytest tests-e2e`; add `NAOQI_E2E_ALLOW_MOTION=1` once the robot has room to move and someone is watching, and `-s` with `NAOQI_E2E_INTERACTIVE=1` to see the prompts.

A test of the `sim` backend itself (`tests-e2e/test_live_sim.py`, skipped on `real`) checks against the session's sim what only a running naoqi-sim shows: `spawn: "auto"` borrows it and leaves it running after `stop()`, `spawn: "always"` refuses it, and a config of the other version is refused.

## Tooling

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

None currently. CI runs the fast tier and, on a headless sim, the live tier ([ci.md](ci.md)); the live tier on a robot stays a local command. What the live tier hasn't confirmed yet is tracked in [analysis/](../analysis/), not here.
