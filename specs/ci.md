---
code:
  - .github/workflows/ci.yml
  - pyproject.toml
tests:
---

# Continuous integration

**Status:** Stable

## Purpose

The verification gate of [AGENTS.md](../AGENTS.md) — lint, type check, tests — runs on GitHub's hosted runners for every pull request and every push to `main`, so it is a machine's verdict on each change and not only a local command. CI runs what needs no hardware and no credentials ([testing.md](testing.md)): the static checks and the fast tier. Like [testing.md](testing.md) this is a cross-cutting practice, not a runtime concept: nothing here ships in the library, and the one file that implements it is the workflow.

## Decided

### The runner

- **GitHub-hosted Linux, the free tier.** Every job runs on `ubuntu-24.04`, pinned by name rather than `ubuntu-latest`, so the image moves only when the pin is bumped on purpose. No self-hosted runner.
- **CI is the project's Linux target.** Development happens on macOS; the runner is where the bridge's Linux paths are exercised — notably the Linux x86_64 `qi` wheel, which `uv sync` installs there ([project.md](project.md)), so the fast-tier tests gated on `pytest.importorskip("qi")` run on the runner. A Linux-only failure is a bridge bug to fix, not a reason to leave Linux out.
- **One Python**, 3.12 — the floor of `requires-python`, the version `.python-version` names; uv installs it on the runner.
- **No system packages.** Nothing in the dependency tree builds from source or needs a system library on Linux, so the jobs install nothing with apt.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main`, and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
|---|---|
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check .`, `pyright` — the static gate |
| `fast-tier` | the same environment; `pytest` — the fast tier, `tests/` only (`testpaths`) |

The two jobs run side by side, each on its own runner, and neither waits on the other: a run takes as long as its slower job. Each job sets up its own environment; with uv's cache that costs seconds.

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
- **The status checks to require on `main`** are `check` and `fast-tier`. Requiring them is a repository setting on GitHub, outside the repo.

## Relationship to the other specs

- **[testing.md](testing.md):** the two tiers and the no-credentials fast tier CI runs. CI is the hosted run of that strategy, with no rule of its own about what a test does.
- **[project.md](project.md):** the `qi` platform dependency the Linux runner installs, the tooling the `check` job runs, `.github/workflows/` in the repo shape.
- **[AGENTS.md](../AGENTS.md):** the verification gate CI automates.

## Open questions

1. **A live job against a simulated Nao.** Once a Nao sim exists, an `e2e-sim` job runs `pytest tests-e2e -rs` against it beside the two jobs above, with its own expected-skips list. Deferred until the sim is built.
2. **A Python matrix.** `requires-python` admits 3.13 too, and `qi` ships a cp313 wheel; a second fast-tier entry on 3.13 would cover it. Deferred until a 3.13-only regression shows the need.
3. **A macOS job.** The developers' platform and the other `qi` wheel (arm64); free on a public repo. Deferred until a macOS-only regression reaches `main`.
