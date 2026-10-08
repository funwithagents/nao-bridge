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

Nao Bridge's testing strategy — the two-tier structure and what a good test looks like. It's a **cross-cutting practice**, not a runtime concept: nothing here ships in the library. It exists as a spec so the decisions have one honest home that stays in sync with the setup, rather than living half in [project.md](project.md) (the tooling choices) and half in [AGENTS.md](../AGENTS.md) (the operational how-to). The concrete shell commands to run each tier live in [AGENTS.md](../AGENTS.md) "Testing".

## Two tiers, physically separated

Tests split into two directories, and the split is structural — a directory boundary, not a marker or an opt-out flag:

| Tier | Directory | Network | Deterministic | Runs by default |
|---|---|---|---|---|
| Unit / integration | `tests/` | never | yes | **yes** |
| Live / e2e | `tests-e2e/` | real service | no | **no** |

- **`tests/` is the normal dev loop.** Fast, deterministic, no real network, no credentials. `pyproject.toml`'s `testpaths = ["tests"]` points the default `uv run pytest` here, so this is what runs on every change and what any contributor or CI can run with zero credentials.
- **`tests-e2e/` is opt-in.** It calls a real external service — network, credentials, non-deterministic output — so it is deliberately *not* collected by the default run. Because `testpaths` already excludes it, no pytest marker or `--run-e2e` flag is needed: the physical separation is the whole mechanism. Run it explicitly (`uv run pytest tests-e2e`).

The `tests/` tier mirrors the `src/nao_bridge/` module layout (`test_<module>.py`, plus the `test_project_map.py` drift-guard); `tests-e2e/` is organized around live scenarios rather than modules.

## What a good test asserts

- **Functional, not tautological.** Exercise what a feature actually does — inputs → outputs, state changes, side effects — not that it runs or matches its own signature. A test that would pass against a broken implementation (asserting a constant, that an object isn't `None`, that a mock was called) isn't worth writing.
- **Drive the public API like a real caller.** Prefer exercising the public surface the way a consumer would over reaching into internals; assert on the observable result.
- **In the e2e tier, assert on behavior, not exact output.** Real service responses vary run to run, so a live test asserts a robust property ("a non-empty result came back", "the side effect happened"), never a specific string.

## Instant fake behaviors

The fake's behaviors last `FakeNaoRobot.DEFAULT_BEHAVIOR_DURATION_S` (5 s) so that demos and client development see them running and stoppable ([robot.md](robot.md)). In the fast tier that would make every dance or app call wait 5 s, so an autouse fixture in `tests/conftest.py` sets the class default to `0.0` for every test.
- A test that needs a running behavior sets `behavior_duration_s` on its fake instance (reached through `bridge.robot`).
- A test that checks the real default is marked `@pytest.mark.fake_behavior_durations`, which the fixture leaves alone.
- Tests that start a server in a subprocess don't get the fixture, so they don't run behaviors.

## Test isolation

The package holds no process-global or singleton state, so neither tier has a reset fixture today. If one appears, both tiers carry an identical autouse fixture (in each tier's `conftest.py`) that resets it before and after every test, duplicated rather than shared because `tests-e2e/` isn't a package that imports from `tests/`. The fast tier's one autouse fixture, the instant fake behaviors above, is deliberately not mirrored: the live tier has no fake.

## Live tier: skip without credentials

A live test needs real credentials, and it must **skip — never fail** — when they're absent, so you exercise only the services you hold keys for and a contributor (or CI) with none is never broken. `tests-e2e/support.require_env(NAME)` implements this: it returns the env var or calls `pytest.skip(...)` when it's unset. Credentials come from the environment, never committed.

For Nao Bridge the live service is a **real Nao robot**: e2e tests take its address from `require_env("NAO_IP")` (optional `NAO_PORT`, default 9559) and also need the `qi` wheel installed. The fast tier never needs a robot — it runs `NaoBridge` and both servers on the `fake` backend (`FakeNaoRobot`, reached through `bridge.robot`), and checks `RealNaoRobot`'s connection rules against a stub `qi` module.

## Tooling

- **`pytest`** is the runner; **`ruff`** lints/formats; **`pyright`** (`standard` mode) type-checks. All three are the gate after any change — lint, type check, and tests must pass before work is considered done (see [AGENTS.md](../AGENTS.md), "Verification").
- **`pyright` covers test code too:** its `include` is `src`, `tests`, and `tests-e2e`, so tests are type-checked alongside the library rather than being a blind spot.

## Open questions

1. **CI wiring.** Nothing here sets up continuous integration. The default `tests/` tier is CI-ready (deterministic, no credentials), and the e2e tier is designed to skip cleanly when keys are absent — but actually running either on a hosted runner is unbuilt. Today all testing is a local, manual command.
