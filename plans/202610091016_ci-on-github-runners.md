# CI on GitHub's hosted runners

**Status:** Done

Implements [specs/ci.md](../specs/ci.md) in full: `.github/workflows/ci.yml` with the `check` and `fast-tier` jobs, side by side on every pull request and push to `main`, and the project's first Linux run. It deliberately leaves out a live job against a simulated Nao (deferred until the sim is built — [ci.md](../specs/ci.md) open question 1) and branch protection (a GitHub setting), noted in Verification.

## Scope

- `.github/workflows/ci.yml` (new) — the two jobs.
- `specs/ci.md` (new) — `Stable` while this plan is open, `Implemented` at the end; its row in `specs/_index.md`.
- `specs/testing.md` — open question 1 ("CI wiring") closed with a pointer to `ci.md` (editorial, status kept).
- `specs/project.md` — `.github/workflows/` in the repo shape (editorial, status kept).
- `AGENTS.md` — a `.github/workflows/` row in the top-level layout table; a line under "Verification" naming CI as the same gate on a runner.
- `plans/_index.md`, this file — status.

## Steps

1. **Spec and docs.** `specs/ci.md` written `Stable`, indexed; `testing.md`, `project.md`, `AGENTS.md` edited.
2. **The workflow**, as [ci.md](../specs/ci.md) "The workflow" specifies: `on: pull_request`, `push: branches: [main]`, `workflow_dispatch`; `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`; `runs-on: ubuntu-24.04`, `timeout-minutes: 10` on both jobs; `actions/checkout@v7`, `astral-sh/setup-uv@v7` with `enable-cache: true` and `cache-dependency-glob: uv.lock`; `uv sync --locked`.
   - `check`: `ruff check .`, `ruff format --check .`, `pyright`.
   - `fast-tier`: `pytest -rs` (skips printed, so a qi-gated test skipping on the runner shows in the log).
3. **Local check** green (see Verification); `tests/test_project_map.py` passes with `ci.md`'s frontmatter pointing at the new workflow.
4. **The Linux shakeout, on GitHub.** Push a branch, open a pull request, read both jobs. Expected risk points, Linux being new to the project:
   - the Linux x86_64 `qi` wheel (`manylinux_2_34`) installing on Ubuntu 24.04 (glibc 2.39) and importing;
   - the two qi-gated tests that skip on a machine without `qi` and now run: `test_libqi_logs_never_reach_the_mcp_client` (asserts libqi's `qi.path.sdklayout` log line lands on stderr — the wording may differ on Linux) and the WebSocket server's real-backend-at-a-closed-port test;
   - the WebSocket server's LAN-IP probe and loopback binds on a runner.
   A failure that is a bridge Linux bug is fixed in `src/` with its test and recorded under "Linux shakeout" below, with the spec it touches. Done when both jobs are green twice, the second run from warm caches; durations recorded under "Measurements".
5. **Statuses.** `specs/ci.md` → `Implemented` (file and index); this plan `Done` (file and index).

## Verification

- Locally: `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` all clean.
- On GitHub: `check` and `fast-tier` green on the pull request, twice; the fast-tier log shows no skip (the runner has `qi`, so the qi-gated tests run).
- Owner's step, outside the repo: require `check` and `fast-tier` as status checks on `main` in the repository settings.

## Linux shakeout

What the runner found that the Mac never had — one line per finding: the symptom, the fix, the spec it touches.

- **Nothing needed a fix.** Both jobs were green on the first run ([PR #5](https://github.com/funwithagents/nao-bridge/pull/5)). The Linux x86_64 `qi` wheel installed from the fork's release and imported; the two qi-gated tests ran and passed, `qi.path.sdklayout` included, so the fast tier ran whole, with no skip.
- **uv's build-backend warning, not acted on.** The runner's uv (0.12.24, latest from `setup-uv`) prints that `uv_build>=0.11.29,<0.12.0` does not contain its version; the build succeeds with a fetched 0.11 backend. A bump of that bound is a `pyproject.toml` change for a later dependency refresh, not CI's.
- **Cache-save race, harmless.** Both jobs compute the same `setup-uv` cache key; the second to finish logs `Unable to reserve cache ... another job may be creating this cache` and the cache is saved once. Left as is.

## Measurements

Run `37904491769`, second attempt (warm caches, cache restored in both jobs): `check` 14 s, `fast-tier` 16 s (pytest 4.2 s, 139 passed), the run about 16 s end to end, both jobs side by side. The first, cold attempt took 14 s per job as well: the environment is small enough that the cache hardly matters.
