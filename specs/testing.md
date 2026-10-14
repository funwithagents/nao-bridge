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

**Status:** Updated

## Purpose

naoqi-bridge's testing strategy — the two-tier structure and what a good test looks like. It's a **cross-cutting practice**, not a runtime concept: nothing here ships in the library. It exists as a spec so the decisions have one honest home that stays in sync with the setup, rather than living half in [project.md](project.md) (the tooling choices) and half in [AGENTS.md](../AGENTS.md) (the operational how-to). The concrete shell commands to run each tier live in [AGENTS.md](../AGENTS.md) "Testing".

## Two tiers, physically separated

Tests split into two directories, and the split is structural — a directory boundary, not a marker or an opt-out flag:

| Tier | Directory | Network | Deterministic | Runs by default |
|---|---|---|---|---|
| Unit / integration | `tests/` | never | yes | **yes** |
| Live / e2e | `tests-e2e/` | real service | no | **no** |

- **`tests/` is the normal dev loop.** Fast, deterministic, no real network, no Docker, no robot. `pyproject.toml`'s `testpaths = ["tests"]` points the default `uv run pytest` here, so this is what runs on every change and what any contributor or CI can run with no target.
- **`tests-e2e/` is opt-in.** It runs against a live Naoqi — a sim in Docker or a robot on the network, non-deterministic output — so it is deliberately *not* collected by the default run. Because `testpaths` already excludes it, no pytest marker or `--run-e2e` flag is needed: the physical separation is the whole mechanism. Run it explicitly (`uv run pytest tests-e2e`).

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

## Live tier: skip without a target

A live test needs a Naoqi to run against, and it must **skip — never fail** — when there is none, so a contributor without Docker or a robot is never broken. A target is missing when there's no `qi` wheel for the platform, no `[sim]` extra, no Docker or no sim images, or, on `real`, no `NAOQI_E2E_IP` or no robot answering at it. The exception is a target asked for by name: with `NAOQI_E2E_TARGET` set, a target that can't run fails the run (below), since whoever set it expects the tests to run. Nothing the tier needs is secret: the robot's address comes from the environment.

For naoqi-bridge the live service is a Naoqi: a **simulated Nao** by default, or a **real Nao robot**. Either way the tier needs the `qi` wheel installed. The fast tier never needs a robot — it runs `NaoqiBridge` and both servers on the `fake` backend (`FakeNaoqiRobot`, reached through `bridge.robot`), and checks `RealNaoqiRobot`'s connection rules against a stub `qi` module.

## Live tier: the harness

The live tier runs on the bridge's shipped harness, `naoqi_bridge.testing` ([testing_support.md](testing_support.md)): `tests-e2e/conftest.py` imports its plugin, so the tier exercises the exact code a consumer gets. The harness owns the mechanics: the environment variables, the session's sim, the capability probe, the `requires` marker, `live_config` / `live_session`. This spec owns how the bridge's own tier uses them.

- **One target per run**, `NAOQI_E2E_TARGET`: `sim` when unset, a headless naoqi-sim the session starts and owns, of the version `NAOQI_E2E_SIM_VERSION` names (2.1 when unset); or `real`, the Nao at `NAOQI_E2E_IP`. The images are never built by the tier: `uv run naoqi-sim fetch-and-build-images` once per machine.
- **A sim that can't run** (no `[sim]` extra, no Docker, images missing, a naoqi-sim already running) skips every test when `NAOQI_E2E_TARGET` is unset, so a contributor without Docker is never broken, and fails the run when it's set, as CI does ([ci.md](ci.md)).
- **Each test runs its own bridge** under `asyncio.run`, since a bridge's streams belong to the loop that started it, with the streams it asks for (`live_config(...)`), borrowing the session's sim (`spawn: "never"`). A test that drives the sim itself (plays into its microphone) takes `live_target.sim`. A test about the robot itself (whether a behavior is still running) may ask Naoqi directly through `bridge.robot`.
- **The tier runs serially** (pytest's default here): one sim per machine, one robot.

## Live tier: capabilities

A live test says what it needs with `@pytest.mark.requires(...)`, never which target it's on: no test reads `NAOQI_E2E_TARGET` or the NAOqi version to decide whether to run. The capability vocabulary and the probes are [testing_support.md](testing_support.md)'s. Two of its kinds matter here:

- **Probed** capabilities say what the target offers: the sim has no dance, a robot has touch sensors.
- **Declared** capabilities are what the person running the tests vouches for. They replace the tier's former levels of risk, and the flags that switched those levels on keep their names and now declare them: `room_to_move` (the motion level, `NAOQI_E2E_ALLOW_MOTION=1`; always held on a sim), `person_present` (the interactive level, `NAOQI_E2E_INTERACTIVE=1`) and `display` (the viewer test, `NAOQI_E2E_VIEWER=1`).

| Test | Requires |
|---|---|
| `test_live_robot.py`, `test_live_verbs.py`, the MCP server test, cancelling a `say`, cancelling a `start()`, the joints stream | nothing: any target |
| The audio stream at 16 kHz mono | `audio_in` |
| A 440 Hz tone played into the sim's microphone reaches `audio_input()` | `audio_inject` |
| A head touch reaches `on_touch` | `touch_sensors`, `person_present` |
| Motors, postures and breathing; cancelling a reaction or a `stand_up` | `room_to_move` |
| A body action and a reaction run to their end; cancelling a body action | `room_to_move`, `body_actions` |
| `stop_dance`; cancelling a dance (both cases) | `room_to_move`, `dances` |
| An app runs until `stop_app` ends it; cancelling `run_app` stops it on the robot (new: the app verbs have no live test yet) | `room_to_move`, `apps` |
| The WebSocket server, whose connect ritual wakes the robot | `room_to_move`, `audio_in` |
| `test_live_sim.py`: the `sim` backend's own rules against the session's sim | `sim` |
| `test_live_viewer.py`: the bridge's viewer opens and closes ([viewer.md](viewer.md)) | `display` |

A test that moves the robot is marked `room_to_move`, and `live_session(..., motion=True)` fails one that isn't. `test_a_body_verb_at_rest_says_to_wake_the_robot_first` still skips at run time when it finds the motors on: that is the robot's state, not a capability.

**Running it.**
- `uv run pytest tests-e2e -rs` runs everything a headless 2.1 sim allows, holding it to the `sim` profile ([testing_support.md](testing_support.md) "Profiles"). `NAOQI_E2E_SIM_VERSION=2.8` runs the same on 2.8, and `NAOQI_E2E_SIM_VIEWER=1` runs it with the sim's window.
- On a robot, `NAOQI_E2E_TARGET=real NAOQI_E2E_IP=… NAOQI_E2E_PROFILE=nao uv run pytest tests-e2e -rs` runs what doesn't move the limbs. The `nao` profile fails the run when the robot lacks what a stock Nao has, such as a catalog that came back without the `dialog_move_arms` actions.
- Add `NAOQI_E2E_ALLOW_MOTION=1` once the robot has room to move and someone is watching, and `NAOQI_E2E_INTERACTIVE=1`, with `-s` to see the prompts, when someone is at the robot.
- `NAOQI_E2E_VIEWER=1` runs the viewer test on either target, locally.

Live tests also **measure**. Each cancellation test records how long its cancel took to return, and the audio test records the chunk size Naoqi really pushes ([microphone.md](microphone.md) open question). `tests-e2e/conftest.py` prints these measurements in the run's terminal summary, after the harness's `live target` section, so the stop retry interval ([bridge.md](bridge.md) "How a spanning verb stops") can be tuned on real numbers.

## Tooling

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

None currently. CI runs the fast tier and, on a headless sim, the live tier ([ci.md](ci.md)); the live tier on a robot stays a local command. What the live tier hasn't confirmed yet is tracked in [analysis/](../analysis/), not here.
