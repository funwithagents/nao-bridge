# Live tier on capabilities

**Status:** In progress

Implements [testing_support.md](../specs/testing_support.md) and the updated live-tier sections of [testing.md](../specs/testing.md), [ci.md](../specs/ci.md) and [project.md](../specs/project.md). It delivers the shipped harness `naoqi_bridge.testing`:
- capabilities, probed or declared;
- the `requires` marker;
- profiles of expected capabilities;
- `live_config` / `live_session`.

It moves the bridge's own live tier onto that harness, with live tests for the app verbs. It leaves out the capabilities listed under the spec's Open questions (`touch_inject`, `inertial`, the robot model), consumer-defined profiles and a `fake` target.

## Scope

- `src/naoqi_bridge/testing/__init__.py`: the public surface (`LiveTarget`, `requires_caps`, `live_config`, `live_bridge_dict`, `live_session`).
- `src/naoqi_bridge/testing/capabilities.py`: the vocabulary, the profiles, the probes, the settings parsing, the needs check and its skip reasons.
- `src/naoqi_bridge/testing/target.py`: the environment (`LiveSettings`), `LiveTarget`, the session's sim, opening a target (acquire, probe, expected check), the config helpers and `live_session`.
- `src/naoqi_bridge/testing/plugin.py`: the pytest plugin: the `live_target` fixture, the `requires` marker (registration, collection check, setup gate), the `live target` summary.
- `pyproject.toml`: the `[test]` extra, `naoqi-bridge[sim,test,viewer]` in the dev group, `-p pytester` for the fast tier's plugin tests.
- `tests/test_testing.py`: the fast-tier tests of the harness.
- `tests-e2e/conftest.py`: loads the plugin; keeps the measurements summary.
- `tests-e2e/support.py`: reduced to what is the bridge's own (measurements, catalog pickers, Naoqi reads).
- `tests-e2e/test_live_*.py`: gated with `@pytest.mark.requires(...)`, with no `TARGET` reads and no `importorskip("qi")`. New app tests in `test_live_motion.py` and `test_live_cancellation.py`.
- `AGENTS.md`: a project map row for `src/naoqi_bridge/testing/`.
- `specs/testing_support.md`: frontmatter on the new files.
- Spec and plan statuses, the indexes and the overview.

## Steps

1. **`capabilities.py`.**
   - Define the probed names, and the declared names, each with its flag and meaning.
   - Define `PROFILES` (`sim`, `nao`, `none`).
   - `probe_capabilities(session, catalog, *, owns_fake_audio)` returns the caps and the NAOqi version from a qi session (services, ALMemory, ALSystem) and the catalog. A probe that raises means the capability is absent, logged as a warning.
   - `CapabilitySettings` and `read_capability_settings(env, target)` raise `pytest.UsageError` on unknown names, on a declared probed name, and on an unknown profile.
   - `missing_reason(caps, needs)` returns the skip message.
2. **`target.py`.**
   - `LiveSettings` / `read_settings(env)`, and `live_settings()`, which caches the process's settings.
   - `LiveTarget`.
   - `open_target(settings)`: on `sim`, the session sim with `spawn: "always"` on its own loop thread. Then a probe bridge (which checks the target answers), the harness's own `qi.Session`, the probe, and the expected check (`check_expected`).
   - The skip-or-fail rule when the target can't run.
   - `live_config`, `live_bridge_dict`, and `live_session`, which fails on `motion=True` without `room_to_move`.
3. **`plugin.py`.**
   - `pytest_configure` registers the marker and reads the settings.
   - `pytest_collection_modifyitems` raises `UsageError` on unknown names in a marker.
   - The session `live_target` fixture (autouse).
   - The function-scoped autouse gate.
   - `pytest_terminal_summary` prints the `live target` section.
4. **`__init__.py`**, `pyproject.toml` and `uv lock`.
5. **The live tier.**
   - The conftest loads the plugin with `config.pluginmanager.import_plugin`, since a non-root conftest can't use `pytest_plugins`.
   - Remove the target reads and level helpers from `support.py`.
   - Mark each test as [testing.md](../specs/testing.md) "Live tier: capabilities" says.
   - Add the app tests.
6. **Fast tier**, `tests/test_testing.py`:
   - The probes on a 2.1 sim, a 2.8 sim and a robot shape, and with a probe that raises.
   - The settings rules.
   - `check_expected`.
   - The marker through `pytester` (met, a missing probed capability, a missing declared one, a typo).
   - `live_session` on the fake: refuses motion without `room_to_move`, and wakes then rests with it.
7. **Docs.** `AGENTS.md` map, the spec frontmatter, statuses.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest`.
- The live tier on a local headless sim, 2.1 and 2.8 (`uv run pytest tests-e2e -rs`).
  - The `live target` summary shows the `sim` profile met.
  - Only the dance, body action, app, touch and viewer tests skip, each naming its capability.
- `NAOQI_E2E_PROFILE=nao` on a sim fails the run, naming the missing capabilities (`touch_sensors`, `body_actions`).
- Then mark this plan `Done`, and move [testing_support.md](../specs/testing_support.md), [testing.md](../specs/testing.md), [ci.md](../specs/ci.md) and [project.md](../specs/project.md) to `Implemented`.
