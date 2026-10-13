---
code:
  - .github/workflows/ci.yml
  - pyproject.toml
tests:
---

# Continuous integration

**Status:** Updated

## Purpose

The verification gate of [AGENTS.md](../AGENTS.md) — lint, type check, tests — runs on GitHub's hosted runners for every pull request and every push to `main`, so it is a machine's verdict on each change and not only a local command. CI runs what needs no hardware and no credentials ([testing.md](testing.md)): the static checks and the fast tier. Like [testing.md](testing.md) this is a cross-cutting practice, not a runtime concept: nothing here ships in the library, and the one file that implements it is the workflow.

## Decided

### The runner

- **GitHub-hosted runners, the free tier.** `check` runs on `ubuntu-24.04`; `fast-tier` runs on `ubuntu-24.04`, `macos-15` and `windows-2025`, the three platforms with a `qi` wheel ([project.md](project.md)). Each image is pinned by name rather than `*-latest`, so it moves only when the pin is bumped on purpose. No self-hosted runner.
- **CI is where every platform is exercised.** Development happens on macOS; the runners are where the bridge's Linux and Windows paths run. Each one's `qi` wheel installs with `uv sync`, so the fast-tier tests gated on `pytest.importorskip("qi")` run on all three, including the MCP server's stdout guard against libqi's real console log ([naoqi-mcp-server.md](naoqi-mcp-server.md)). A failure on one platform is a bridge bug to fix, not a reason to leave the platform out.
- **One Python**, 3.12 — the floor of `requires-python`, the version `.python-version` names; uv installs it on the runner.
- **No system packages.** Nothing in the dependency tree builds from source or needs a system library, so the jobs install nothing beyond the sync.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main`, and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
|---|---|
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check .`, `pyright` — the static gate |
| `fast-tier` | a matrix over the three runners above, `fail-fast: false`; the same environment; `pytest -rs` — the fast tier, `tests/` only (`testpaths`) |

The jobs and the matrix entries run side by side, each on its own runner, and none waits on another: a run takes as long as its slowest job. One platform failing leaves the others running, so a run shows every platform's verdict. Each job sets up its own environment; with uv's cache that costs seconds.

- **`--locked`.** The sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock or not at all.
- **The dev group installs** with the sync (uv's default groups); there are no other groups.
- **The format check covers the whole repo** (`.`): `specs/` and `plans/` are excluded in `pyproject.toml`, so `ruff format` touches Python files only — the same command as a local run.
- **uv's cache** is kept by `astral-sh/setup-uv` (`enable-cache`, keyed on `uv.lock`).
- **Timeouts.** Each job carries a `timeout-minutes` (10) well under GitHub's default, so a hung test fails the job in minutes rather than hours.

### What CI does not run

- **The live tier (`tests-e2e/`).** It needs a real Nao (`NAO_IP`), which no runner has; its tests would all skip, so the job would prove nothing. A live job against a simulated Nao is a later addition, once a sim exists (open question 1).
- **A real robot**, ever: that stays a local command.

### Secrets and protection

- **No secret is required**, and none is used: forks' pull requests run the same jobs as the owner's.
- **The status checks to require on `main`** are `check` and the three `fast-tier` entries. Requiring them is a repository setting on GitHub, outside the repo.

## Relationship to the other specs

- **[testing.md](testing.md):** the two tiers and the no-credentials fast tier CI runs. CI is the hosted run of that strategy, with no rule of its own about what a test does.
- **[project.md](project.md):** the `qi` platform dependency each runner installs, the tooling the `check` job runs, `.github/workflows/` in the repo shape.
- **[AGENTS.md](../AGENTS.md):** the verification gate CI automates.

## Open questions

1. **A live job against a simulated Nao.** Once a Nao sim exists, an `e2e-sim` job runs `pytest tests-e2e -rs` against it beside the two jobs above, with its own expected-skips list. Deferred until the sim is built.
2. **A Python matrix.** `requires-python` admits 3.13 too, and `qi` ships a cp313 wheel; a second fast-tier entry on 3.13 would cover it. Deferred until a 3.13-only regression shows the need.
