# Robot backends in their own modules

**Status:** Done

Implements the edit to `specs/robot.md` ("A Protocol, not a union over the SDK object"): each backend lives in its own module and the real one is named for its backend. `QiNaoRobot` becomes `RealNaoRobot` in `real_robot.py`, `FakeNaoRobot` moves to `fake_robot.py`, and `robot.py` keeps only what they share plus `build_robot`. No behavior changes.

## Scope

- `src/nao_bridge/robot.py` — keeps the `NaoRobot` Protocol, callback types, shared constants, `RobotConnectionError`, `build_robot` (imports the backends lazily).
- `src/nao_bridge/real_robot.py` (new) — `RealNaoRobot` (was `QiNaoRobot`) and its audio sink.
- `src/nao_bridge/fake_robot.py` (new) — `FakeNaoRobot` and its package list (`_animation_package` renamed `_sub_behaviors_package`; sub-behavior packages get names and descriptions).
- `tests/test_robot.py` split into `test_robot.py` (backend selection), `test_real_robot.py`, `test_fake_robot.py`; `tests-e2e/test_real_robot.py` renamed `test_live_robot.py` so the two tiers don't share a module name.
- Imports of `FakeNaoRobot` in `tests/`; `AGENTS.md` project map; `specs/robot.md`, `specs/microphone.md` frontmatter; `RealNaoRobot` naming in specs.

## Steps

1. Move each backend's region of `robot.py` to its module; rename `QiNaoRobot` → `RealNaoRobot`.
2. Split the tests along the same lines; update imports.
3. Update the project map, spec frontmatter and spec wording.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` all clean, including `tests/test_project_map.py` (map and frontmatter).
