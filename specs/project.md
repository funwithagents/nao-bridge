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

- **Python version:** 3.12 or 3.13 (`requires-python = ">=3.12,<3.14"`), capped by the `qi` wheels, which exist for CPython 3.12 and 3.13 only.
- **Package layout:** `src/` layout — `src/nao_bridge/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`.
- **Runtime dependencies:** `mcp` pinned to `<2` (the server uses the v1 `FastMCP` API, removed in mcp 2.x) and `websockets`.
- **`qi` is a platform dependency.** `qi==3.1.6` is declared in `dependencies` with a platform marker, so it installs only where a wheel exists. The wheels come from the GitHub releases of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python/releases) fork, wired through `[tool.uv.sources]`, one URL per platform and Python version; PyPI's `qi` is the older 3.1.5.

  | Platform | `qi` | Backends |
  |---|---|---|
  | macOS arm64, Linux x86_64 (CPython 3.12 / 3.13) | installed by `uv sync` | `real` and `fake` |
  | Windows, macOS x86_64, Linux aarch64 | not installed (no wheel) | `fake` only |

  `[tool.uv] environments` lists all five platforms, so the lock resolves and `uv sync` works on each; the marker leaves `qi` out where there is no wheel. `QiNaoRobot` still imports `qi` lazily on connect, so `nao_bridge` imports everywhere. Where `qi` is absent, the `real` backend raises `RobotConnectionError` explaining that this platform runs the fake only ([robot.md](robot.md)). Declaring `qi` also means `uv sync` keeps it; a hand-installed wheel would be removed by the next sync.
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

1. **Installing with pip.** pip ignores `[tool.uv.sources]`, so `pip install` from the repo would look for `qi==3.1.6` on PyPI (which has only 3.1.5) and fail on macOS arm64 / Linux x86_64. Listing the wheel URLs as direct references in `dependencies` (one per platform and Python version) would work for pip and uv alike, but would rule out publishing to PyPI. Deferred: uv is the supported installer.
