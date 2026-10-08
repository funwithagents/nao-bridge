# Implementation plans

Implementation plans for Nao Bridge — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202610071850_existing-code-to-green.md](202610071850_existing-code-to-green.md) | Bring pre-SDD code through lint/type-check/tests, package imports + entry points, fix `stop_expressive_reaction` (delivered by the robot/bridge split) | Done |
| [202610071906_robot-bridge-split.md](202610071906_robot-bridge-split.md) | Robot seam / bridge architecture: `robot.py` seam (`real`/`fake`) + `NaoBridge` in `bridge.py`; servers ported; fast-tier tests | Done |
| [202610081509_config-and-stream-apis.md](202610081509_config-and-stream-apis.md) | `NaoBridgeConfig` + server configs + `--config` CLIs; stream APIs replacing callbacks (touch `Event`, joints `Observable`, mic feed with `audio_input()` subscribers) | Done |
| [202610081629_qi-as-a-platform-dependency.md](202610081629_qi-as-a-platform-dependency.md) | `qi==3.1.6` declared from the fork's wheels on macOS arm64 / Linux x86_64 (CPython 3.12–3.13); other platforms install fake-only | Done |
| [202610081653_mcp-stdout-reserved-for-the-protocol.md](202610081653_mcp-stdout-reserved-for-the-protocol.md) | libqi's native console log no longer corrupts the MCP stdio channel: fd 1 → stderr while serving, the transport on a private dup | Done |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
