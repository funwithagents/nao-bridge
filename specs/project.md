---
code:
  - pyproject.toml
  - .gitattributes
tests:
  - tests/test_project_map.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the naoqi-bridge project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, and development tooling.

## Decided

- **Python version:** 3.12 or 3.13 (`requires-python = ">=3.12,<3.14"`), capped by the `qi` wheels, which exist for CPython 3.12 and 3.13 only.
- **Package layout:** `src/` layout — `src/naoqi_bridge/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`.
- **Runtime dependencies:** `mcp` pinned to `<2` (the server uses the v1 `FastMCP` API, removed in mcp 2.x) and `websockets`.
- **`qi` is a platform dependency.** `qi>=3.1.8,<4` is declared in `dependencies` with a platform marker, so it installs only where a wheel exists. 3.1.8 is the floor because it fixed the failed connects that 3.1.6 needed retries for ([robot.md](robot.md)). The wheels come from the package index of the [funwithagents/libqi-python](https://github.com/funwithagents/libqi-python) fork on GitHub Pages, `https://funwithagents.github.io/libqi-python/simple/`; PyPI's `qi` is the older 3.1.5.
  - **uv:** a `[[tool.uv.index]]` named `libqi`, `explicit = true` so that only `qi` comes from it, and `qi = { index = "libqi" }` in `[tool.uv.sources]`.
  - **pip** finds it with `--extra-index-url https://funwithagents.github.io/libqi-python/simple/`: pip takes the highest `qi` across indexes, 3.1.8 over PyPI's 3.1.5 (measured with pip in a fresh venv).

  | Platform | `qi` | Backends |
  |---|---|---|
  | macOS 11+ arm64, Linux x86_64 (glibc 2.28+), Windows x64 (CPython 3.12 / 3.13) | installed by `uv sync` | `real` and `fake` |
  | macOS x86_64, Linux aarch64, Windows arm64 | not installed (no wheel) | `fake` only |

  `[tool.uv] environments` lists all five platforms (Windows on any machine), so the lock resolves and `uv sync` works on each; the marker leaves `qi` out where there is no wheel. naoqi-bridge installs even where `qi` doesn't, since the fake backend runs everywhere. `RealNaoqiRobot` still imports `qi` lazily on connect, so `naoqi_bridge` imports everywhere. Where `qi` is absent, the `real` backend raises `RobotConnectionError` explaining that this platform runs the fake only ([robot.md](robot.md)). Declaring `qi` also means `uv sync` keeps it; a hand-installed wheel would be removed by the next sync.
- **The `[sim]` extra** ([sim.md](sim.md)): `naoqi-bridge[sim]` adds `naoqi-sim[viewer]`, with `qi`'s platform marker (naoqi-sim needs `qi`). naoqi-sim is not on PyPI: `[tool.uv.sources]` takes it from `https://github.com/funwithagents/naoqi-sim`, pinned to a commit (`rev`) moved on purpose. uv applies naoqi-sim's own sources to it, so its `qi` comes from the libqi index. pip ignores uv's sources: the extra is uv-only, like naoqi-sim itself.
- **The `[viewer]` extra** ([viewer.md](viewer.md)): `naoqi-bridge[viewer]` adds `naoqi-viewer`, with `qi`'s platform marker (naoqi-viewer needs `qi`). naoqi-viewer is not on PyPI either: `[tool.uv.sources]` takes it from `https://github.com/funwithagents/naoqi-viewer`, pinned to **the commit naoqi-sim pins**, since `naoqi-sim[viewer]` installs naoqi-viewer too and one environment holds one. The two pins move together: bumping naoqi-sim means setting naoqi-viewer to the commit naoqi-sim now pins. uv-only, like `[sim]`.
  - The **`dev` group** includes `naoqi-bridge[sim,test,viewer]`, so a development sync, pyright and every CI job see naoqi-sim (the `sim` and viewer code type-check against their real APIs, and the live tier can run a sim). On the platforms without `qi` the marker leaves it out, and the `sim` code's lazy imports keep the rest working.
  - naoqi-sim's images, Docker and Aldebaran's downloads are never uv's: `uv run naoqi-sim fetch-and-build-images` once per machine.
- **The `[test]` extra** ([testing_support.md](testing_support.md)): `naoqi-bridge[test]` adds `pytest`, for the shipped live-tier harness `naoqi_bridge.testing`; a consumer's live tier on a sim installs `naoqi-bridge[sim,test]`. No platform marker of its own: the harness imports everywhere, and reaches a target where `qi` is.
- **Windows.** Files the package reads are opened as UTF-8 (Windows' default is a legacy code page), and `.gitattributes` checks every text file out with LF (`* text=auto eol=lf`), so a Windows checkout holds the same configs, specs and tests as anywhere else.
- **Console scripts:** `naoqi-mcp-server` and `naoqi-websocket-server` (`[project.scripts]`), run with `uv run <script>`. Modules import each other relatively (`from .bridge import …`), the servers included; `python -m naoqi_bridge.<module>` works too.
- **Linting/formatting:** `ruff`, on its (already broad) default rule set extended with pycodestyle (`E`, `W`), performance (`PERF`) and annotations (`ANN`) — the latter for `src/` only, since test functions don't need return types. Line length is left to the formatter (`E501` off). It also formats Python code fences in Markdown, so `specs/` and `plans/` are excluded (`extend-exclude`): their fences hold design sketches, not code.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that calls real external services. Full strategy is specced in [testing.md](testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`.
- **Repo shape:**
  - `src/naoqi_bridge/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept (this folder).
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `examples/configs/` — ready-to-use server config files ([config.md](config.md)).
  - `tests/` at repo root, mirroring the `src/naoqi_bridge/` module structure.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.
  - `.github/workflows/` — the CI workflow ([ci.md](ci.md)).
  - `.gitattributes` — LF checkouts on every platform (above).

## Open questions

1. **Publishing on PyPI.** naoqi-bridge is installed from its repository. A published wheel would declare `qi>=3.1.8,<4` with its platform marker, which pip resolves through the libqi index above; whether to publish is undecided.
