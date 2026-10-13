---
code:
  - .github/workflows/ci.yml
  - pyproject.toml
tests:
---

# Continuous integration

**Status:** Updated

## Purpose

The verification gate of [AGENTS.md](../AGENTS.md) — lint, type check, tests — runs on GitHub's hosted runners for every pull request and every push to `main`, so it is a machine's verdict on each change and not only a local command. CI runs what needs no hardware and no credentials ([testing.md](testing.md)): the static checks, the fast tier, and the live tier against a simulated Nao the runner builds itself ([sim.md](sim.md)). Like [testing.md](testing.md) this is a cross-cutting practice, not a runtime concept: nothing here ships in the library, and the one file that implements it is the workflow.

## Decided

### The runner

- **GitHub-hosted runners, the free tier.** `check` runs on `ubuntu-24.04`; `fast-tier` runs on `ubuntu-24.04`, `macos-15` and `windows-2025`, the three platforms with a `qi` wheel ([project.md](project.md)). Each image is pinned by name rather than `*-latest`, so it moves only when the pin is bumped on purpose. No self-hosted runner.
- **CI is where every platform is exercised.** Development happens on macOS; the runners are where the bridge's Linux and Windows paths run. Each one's `qi` wheel installs with `uv sync`, so the fast-tier tests gated on `pytest.importorskip("qi")` run on all three, including the MCP server's stdout guard against libqi's real console log ([naoqi-mcp-server.md](naoqi-mcp-server.md)). A failure on one platform is a bridge bug to fix, not a reason to leave the platform out.
- **One Python**, 3.12 — the floor of `requires-python`, the version `.python-version` names; uv installs it on the runner.
- **No system packages for `check` and `fast-tier`.** Nothing in the dependency tree builds from source or needs a system library, so those jobs install nothing beyond the sync. `e2e-sim` adds Mesa's EGL for the headless viewer (below).
- **The live tier on Linux only.** naoqi-sim's NAOqi runs in Linux containers: GitHub's Linux runners run them natively, its macOS runners have no Docker, and its Windows runners run Windows containers only.

### The workflow

One file, `.github/workflows/ci.yml`. It triggers on `pull_request`, on `push` to `main`, and on `workflow_dispatch`. Concurrency is one run per ref: a newer push cancels the older run still in flight.

| Job | What |
|---|---|
| `check` | `uv sync --locked`, then `ruff check .`, `ruff format --check .`, `pyright` — the static gate |
| `fast-tier` | a matrix over the three runners above, `fail-fast: false`; the same environment; `pytest -rs` — the fast tier, `tests/` only (`testpaths`) |
| `e2e-sim` | a matrix over the NAOqi versions (`2.1`, `2.8`) on `ubuntu-24.04`, `fail-fast: false`: restore or build the version's sim images, then `pytest tests-e2e -rs` against a headless sim of that version (below) |

The jobs and the matrix entries run side by side, each on its own runner, and none waits on another: a run takes as long as its slowest job. One platform failing leaves the others running, so a run shows every platform's verdict. Each job sets up its own environment; with uv's cache that costs seconds.

- **`--locked`.** The sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock or not at all.
- **The dev group installs** with the sync (uv's default groups); there are no other groups.
- **The format check covers the whole repo** (`.`): `specs/` and `plans/` are excluded in `pyproject.toml`, so `ruff format` touches Python files only — the same command as a local run.
- **uv's cache** is kept by `astral-sh/setup-uv` (`enable-cache`, keyed on `uv.lock`).
- **Timeouts.** Each job carries a `timeout-minutes` well under GitHub's default (10, and 45 for an `e2e-sim` entry, whose cold image build is the longest step), so a hung test fails the job in minutes rather than hours.

### The `e2e-sim` job

One entry per NAOqi version, each on its own runner, since one sim runs per machine. The bridge is verified on 2.1; the 2.8 entry is where `NaoqiRobot`'s 2.8 gaps show, and it is held to the same bar. In order:

1. **Disk.** The 2.8 image is about 6 GB and its `docker save` archive as much again: the entry first deletes the runner's preinstalled toolchains the project never uses (Android SDK, .NET, GHC, CodeQL), about 25 GB. Both entries do it, so they stay alike.
2. **Sync**: `uv sync --locked`, which installs the `[sim]` extra through the dev group ([project.md](project.md)).
3. **The image data folder** is `$RUNNER_TEMP/image-data` (`NAOQI_SIM_IMAGE_DATA` for the whole job), so the cache below finds naoqi-sim's record of verified images at a known path.
4. **The cache key**, computed from the installed naoqi-sim: `naoqi-<version>-<naoqi-sim version>-<recipes digest>-<hash of naoqi-sim's suite pins>` (`naoqi_sim.docker_images.naoqi_sim_version()`, `recipes_digest()`, and a SHA-256 of `naoqi_sim/suite.py`). The first two are what naoqi-sim compares to the image labels, so the key changes exactly when a start would find the images outdated: moving the naoqi-sim pin to a commit that changed its container recipes rebuilds, one that didn't reuses the cache.
5. **Restore** (`actions/cache/restore`): one archive per version, the `docker save` of the version's NAOqi image and the `tts` image, with `images.json`, naoqi-sim's record of the verified image IDs. On a hit, `docker load`, then the archive is deleted to free its space; the IDs survive the save and load, so naoqi-sim accepts the images as verified.
6. **On a miss**: `uv run naoqi-sim fetch-and-build-images <version>`, which downloads Aldebaran's public suite, builds the images and checks they boot, as on a user's machine; then `docker save` and **save** (`actions/cache/save`) right away, before the tests, so a failing live tier doesn't rebuild next run. The image data (the downloads) are deleted, never cached.
7. **System packages**: `libegl1` and `libgl1-mesa-dri`, Mesa's display-less GL, which the headless viewer renders the sim's camera through.
8. **The live tier**: `uv run pytest tests-e2e -rs` with `NAOQI_E2E_TARGET=sim` (a sim that can't run fails, never skips) and `NAOQI_E2E_SIM_VERSION` set to the entry's version, warnings and errors logged live (`-o log_cli=true --log-cli-level=WARNING`).
9. **On failure**: the end of the sim's container logs (`docker logs` on the `naoqi-sim-*` containers still there).

**Licensing.** The images contain Aldebaran's software, downloaded from its public repositories as a user does. They go to this repository's Actions cache only: nothing is pushed to a registry, attached to a release or uploaded as an artifact.

### Expected skips

The tests that skip by design in `e2e-sim`, the same six on both entries; any other skip there is a fault. Measured on local runs of both versions (21 passed, 6 skipped each).

| Test | Why |
|---|---|
| `test_live_cancellation.py::test_a_cancelled_dance_stops_on_the_robot` (both cases), `test_live_motion.py::test_stop_dance_ends_a_dance_and_its_verb_returns` | No dance: the sim has the `animations` package only ([sim.md](sim.md)) |
| `test_live_cancellation.py::test_a_cancelled_body_action_stops_on_the_robot`, `test_live_motion.py::test_a_body_action_and_a_reaction_run_to_their_end` | No body action, for the same reason |
| `test_live_streams.py::test_a_head_touch_reaches_on_touch` | The interactive level is skipped on a sim: naoqi-sim has no touch input yet |

### What CI does not run

- **A real robot**, ever: the live tier on a robot (`NAOQI_E2E_TARGET=real`) stays a local command.
- **The sim window** (`NAOQI_E2E_SIM_VIEWER`): the runners have no display; the job runs the headless viewer.
- **The live tier on macOS or Windows**: no Linux containers there (above).

### Secrets and protection

- **No secret is required**, and none is used: forks' pull requests run the same jobs as the owner's.
- **The status checks to require on `main`** are `check`, the three `fast-tier` entries and both `e2e-sim` entries. Requiring them is a repository setting on GitHub, outside the repo.

## Relationship to the other specs

- **[testing.md](testing.md):** the two tiers and the no-credentials fast tier CI runs. CI is the hosted run of that strategy, with no rule of its own about what a test does.
- **[project.md](project.md):** the `qi` platform dependency each runner installs, the tooling the `check` job runs, `.github/workflows/` in the repo shape.
- **[sim.md](sim.md):** the `sim` backend and the naoqi-sim images `e2e-sim` builds and caches.
- **[AGENTS.md](../AGENTS.md):** the verification gate CI automates.

## Open questions

1. **A Python matrix.** `requires-python` admits 3.13 too, and `qi` ships a cp313 wheel; a second fast-tier entry on 3.13 would cover it. Deferred until a 3.13-only regression shows the need.
