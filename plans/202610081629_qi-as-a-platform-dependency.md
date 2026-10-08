# `qi` as a platform dependency

**Status:** Done

Implements the edits to `specs/project.md` ("`qi` is a platform dependency", Python version, supported platforms) and `specs/robot.md` (the missing-`qi` error), both `Updated`. `qi==3.1.6` becomes a declared dependency, resolved from the libqi-python fork's GitHub release wheels on the platforms that have one (macOS arm64, Linux x86_64, CPython 3.12 / 3.13). Every other platform installs without it and runs the `fake` backend only. This leaves out installing with pip, which ignores uv's sources; it's recorded as an open question in `project.md`.

## Scope

- `pyproject.toml`:
  - `requires-python = ">=3.12,<3.14"`;
  - `qi==3.1.6` in `dependencies`, with a platform marker;
  - `[tool.uv] environments`: the two `qi` platforms plus Windows, macOS x86_64 and Linux aarch64 (fake only);
  - `[tool.uv.sources] qi`: the four wheel URLs.
- `uv.lock` — re-locked.
- `src/nao_bridge/robot.py` — the missing-`qi` error explains which platforms ship it and that the others are fake-only.
- `specs/project.md`, `specs/robot.md`, `specs/_index.md`, `README.md` ("Dependency with qi python package").

## Steps

1. Spec edits; `project.md` and `robot.md` → `Updated`.
2. `pyproject.toml`, then `uv lock` and `uv sync --dev`. Check `qi` is installed on this machine (macOS arm64, CPython 3.12) and that `import qi` works.
3. Check the lock per platform with `uv pip compile --python-platform`: `qi` from the right wheel on macOS arm64 and Linux x86_64 for 3.12 and 3.13, and absent on Windows, macOS x86_64 and Linux aarch64, with every other dependency resolved.
4. Reword the error message in `QiNaoRobot.connect()`.
5. README: `uv sync` installs `qi` where a wheel exists; the platform table; fake-only elsewhere.
6. Specs → `Implemented`, this plan → `Done`.

## Verification

Done 2026-10-08:
- `qi` 3.1.6 is installed by `uv sync` on this machine (macOS arm64, CPython 3.12).
- `uv pip compile --python-platform` across 5 platforms × 2 Pythons: the right wheel on macOS arm64 and Linux x86_64, no `qi` and no resolution error on Windows, macOS x86_64 and Linux aarch64.
- ruff and pyright are clean, and 98 tests pass. `tests-e2e` skips on `NAO_IP`.
- A `real` config against a closed port now fails inside libqi ("Connection refused" × `connect_tries`), exit 1.
- Side finding, not in scope: libqi writes a `qi.path.sdklayout` warning to stdout on session creation, which reproduces the MCP stdio issue (`nao-mcp-server.md` open question 2) without a robot.

The original checklist:

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest` all clean, with `qi` now installed in the dev environment: the missing-`qi` test still forces the import to fail, and the stub-`qi` tests still replace the module. `uv run pytest tests-e2e` now skips on `NAO_IP` only. `nao-mcp-server` with a `real` config fails on connection (no robot) instead of on the missing `qi`.
