---
code:
  - tests/conftest.py
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

The fake's behaviors last `FakeNaoRobot.DEFAULT_BEHAVIOR_DURATION_S` (5 s), its speech `DEFAULT_SPEECH_DURATION_S` (1 s) and its posture moves `DEFAULT_POSTURE_DURATION_S` (2 s). That way demos and client development see them running and stoppable ([robot.md](robot.md)). In the fast tier it would make every dance, `say` or `stand_up` wait, so an autouse fixture in `tests/conftest.py` sets all three class defaults to `0.0` for every test.
- A test that needs one in flight (a running behavior, a `say` or posture move to cancel) sets `behavior_duration_s`, `speech_duration_s` or `posture_duration_s` on its fake instance (reached through `bridge.robot`).
- A test that checks the real defaults is marked `@pytest.mark.fake_behavior_durations`, which the fixture leaves alone.
- Tests that start a server in a subprocess don't get the fixture, so they don't run behaviors, speech or postures.

## Test isolation

The package holds no process-global or singleton state, so neither tier has a reset fixture today. If one appears, both tiers carry an identical autouse fixture (in each tier's `conftest.py`) that resets it before and after every test, duplicated rather than shared because `tests-e2e/` isn't a package that imports from `tests/`. The fast tier's one autouse fixture, the instant fake behaviors above, is deliberately not mirrored: the live tier has no fake.

## Live tier: skip without credentials

A live test needs real credentials, and it must **skip — never fail** — when they're absent, so you exercise only the services you hold keys for and a contributor (or CI) with none is never broken. `tests-e2e/support.require_env(NAME)` implements this: it returns the env var or calls `pytest.skip(...)` when it's unset. Credentials come from the environment, never committed.

For naoqi-bridge the live service is a **real Nao robot**: e2e tests take its address from `require_env("NAO_IP")` (optional `NAO_PORT`, default 9559) and also need the `qi` wheel installed. The fast tier never needs a robot — it runs `NaoqiBridge` and both servers on the `fake` backend (`FakeNaoRobot`, reached through `bridge.robot`), and checks `RealNaoRobot`'s connection rules against a stub `qi` module.

## Live tier: levels of risk

A live test that moves the robot needs more than its address: someone has to have cleared the floor. So the live tier has three levels, each an opt-in on top of the one before, and a test skips unless its level is switched on:

| Level | Switched on by | What it may do | Modules |
|---|---|---|---|
| **Safe** | `NAO_IP` | Anything that doesn't move the limbs: connect, catalog, eyes, TTS language, speech, basic awareness (motors off), errors, the joints and audio streams, cancelling a `say` | `test_live_robot.py`, `test_live_verbs.py`, `test_live_streams.py`, the safe half of `test_live_cancellation.py`, the MCP half of `test_live_servers.py` |
| **Motion** | `NAO_ALLOW_MOTION=1` | Motors on, postures, breathing, body actions, reactions, a dance, and cancelling them; the WebSocket server, whose connect ritual wakes the robot | `test_live_motion.py`, the motion half of `test_live_cancellation.py`, the WebSocket half of `test_live_servers.py` |
| **Interactive** | `NAO_INTERACTIVE=1` | Asks the person at the robot to act (touch the head) and waits for it | the touch test in `test_live_streams.py` |

A flag is on when it's `1`, `true` or `yes`. `tests-e2e/support.py` holds what the levels share:
- `require_env(name)` and `require_flag(name)`, which skip when the variable or the flag is missing;
- `live_config(...)`, a `real` `NaoqiBridgeConfig` from `NAO_IP` / `NAO_PORT` with the streams a test asks for;
- `live_session(...)`, which runs a bridge on it and leaves the robot as it found it: eyes white and, at the motion level, `rest`;
- the catalog pickers, which take ids from the robot's own catalog (installed dances and apps differ per robot) and skip when it has none.

Each test runs its own session under `asyncio.run`, since a bridge's streams belong to the loop that started it. A test about the robot itself (whether a behavior is still running) may ask Naoqi directly through `bridge.robot`.

Live tests also **measure**. Each cancellation test records how long its cancel took to return, and the audio test records the chunk size Naoqi really pushes ([microphone.md](microphone.md) open question). `tests-e2e/conftest.py` prints these measurements in the run's terminal summary, so the stop retry interval ([bridge.md](bridge.md) "How a spanning verb stops") can be tuned on real numbers. Run the safe level alone with `NAO_IP=… uv run pytest tests-e2e`. Add `NAO_ALLOW_MOTION=1` once the robot has room to move and someone is watching, and `-s` with `NAO_INTERACTIVE=1` to see the prompts.

## Tooling

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

None currently. CI runs the fast tier on GitHub's runners ([ci.md](ci.md)); the live tier stays a local command until a simulated Nao exists. What the live tier hasn't confirmed yet is tracked in [analysis/](../analysis/), not here.
