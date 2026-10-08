# Implementation plans

Implementation plans for Nao Bridge — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202610071900_existing-code-to-green.md](202610071900_existing-code-to-green.md) | Bring pre-SDD code through lint/type-check/tests, package imports + entry points, fix `stop_expressive_reaction` (delivered by the robot/bridge split) | Done |
| [202610072000_robot-bridge-split.md](202610072000_robot-bridge-split.md) | Reachy-style architecture: `robot.py` seam (`real`/`fake`) + `NaoBridge` in `bridge.py`; servers ported; fast-tier tests | Done |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
