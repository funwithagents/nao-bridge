---
code:
  - pyproject.toml
tests:
  - tests/test_project_map.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the Nao Bridge project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, and development tooling.

## Decided

- **Python version:** 3.12+ minimum.
- **Package layout:** `src/` layout — `src/nao_bridge/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`.
- **Runtime dependencies:** `mcp` pinned to `<2` (the server uses the v1 `FastMCP` API, removed in mcp 2.x) and `websockets`.
- **`qi` is an optional, out-of-band dependency.** It isn't on PyPI for current Pythons; users install a platform/Python-specific wheel from the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python/releases) fork (see README). It is therefore *not* declared in `pyproject.toml`; `QiNaoRobot` imports it lazily on connect, and without it the `real` backend raises `RobotConnectionError` rather than faking ([robot.md](robot.md)); the `fake` backend never needs it. The Python floor (3.12) must stay one the fork ships wheels for.
- **Console scripts:** `nao-mcp-server` and `nao-websocket-server` (`[project.scripts]`), run with `uv run <script>`. Modules use package imports (`from nao_bridge.bridge import …`), so `python -m nao_bridge.<module>` works too.
- **Linting/formatting:** `ruff`. It also formats Python code fences in Markdown, so `specs/` and `plans/` are excluded (`extend-exclude`): their fences hold design sketches, not code.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that calls real external services. Full strategy is specced in [testing.md](testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`.
- **Repo shape:**
  - `src/nao_bridge/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept (this folder).
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `examples/configs/` — ready-to-use server config files ([config.md](config.md)).
  - `tests/` at repo root, mirroring the `src/nao_bridge/` module structure.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.

## Open questions

None currently.
