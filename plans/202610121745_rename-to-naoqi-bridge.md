# Rename to naoqi-bridge

**Status:** Done

The toolkit's packages become `naoqi-*` (cross-repository analysis: `nao-sim/analysis/naoqi-rename.md`; after the rename, `naoqi-sim/analysis/naoqi-rename.md`). This plan renames Nao Bridge to naoqi-bridge everywhere a name comes from the package: repository, distribution, import package, the two CLIs and their modules, the `NaoBridge*` and server classes, the specs and docs, and the sim's names where they appear (the planned `sim` backend). It changes no behavior and adds no compatibility alias.

It is independent of the other three repositories: nothing here imports or pins them. It can run before, between or after them; only the prose about the sim waits for naoqi-sim's names to be final (they are, in the analysis).

**Kept** (robot names, not the package's): `NaoRobot`, `RealNaoRobot`, `FakeNaoRobot`, `QiNaoRobot`, `NaoState`, `NaoBehavior`; `NAO_IP`, `NAO_PORT`, `NAO_ALLOW_MOTION`, `NAO_INTERACTIVE` (they address the robot); the MCP server's advertised name `FastMCP("Nao")` (the agent drives a NAO); `<nao-ip>`, `nao-tiny-agent`, `fake-nao-audio` in the README and code; prose about "Nao" the robot. Making the robot names generic is Pepper work. `Done` plans are historical records and stay as written.

## Scope

Names, in replacement order (exact tokens, never a bare `nao`):

| Old | New |
| --- | --- |
| `NaoBridge` (`NaoBridge`, `NaoBridgeConfig`, `NaoBridgeAudio`) | `NaoqiBridge`… |
| `NaoMcpServer`, `NaoMcpServerConfig` | `NaoqiMcpServer`, `NaoqiMcpServerConfig` |
| `NaoWebsocketServer`, `NaoWebsocketServerConfig` | `NaoqiWebsocketServer`, `NaoqiWebsocketServerConfig` |
| `nao_mcp_server`, `nao_websocket_server` | `naoqi_mcp_server`, `naoqi_websocket_server` |
| `nao-mcp-server`, `nao-websocket-server` | `naoqi-mcp-server`, `naoqi-websocket-server` |
| `nao_bridge` | `naoqi_bridge` |
| `nao-bridge`, "Nao Bridge" (the package's display name) | `naoqi-bridge` |
| `nao-sim`, `NaoSim` (prose, target id) | `naoqi-sim`, `NaoqiSim` |

Files:

- `src/nao_bridge/` → `src/naoqi_bridge/` (`git mv`); `nao_mcp_server.py` → `naoqi_mcp_server.py`, `nao_websocket_server.py` → `naoqi_websocket_server.py`
- `tests/test_nao_mcp_server.py` → `tests/test_naoqi_mcp_server.py`, `tests/test_nao_websocket_server.py` → `tests/test_naoqi_websocket_server.py`; imports in every test and in `tests-e2e/`
- `specs/nao-mcp-server.md` → `specs/naoqi-mcp-server.md`, `specs/nao-websocket-server.md` → `specs/naoqi-websocket-server.md` (a spec is named like its module); every link to them
- `pyproject.toml` — `name = "naoqi-bridge"` (hyphenated like the others), version `0.1.0` (unchanged), scripts `naoqi-mcp-server = "naoqi_bridge.naoqi_mcp_server:main"`, `naoqi-websocket-server = "naoqi_bridge.naoqi_websocket_server:main"`, the description
- `uv.lock` — regenerated
- `src/naoqi_bridge/real_robot.py` — the install hint naming the package; `fake_robot.py` — the comment naming the sim
- `.github/workflows/ci.yml` — names, if any
- `examples/configs/` — `README.md` (commands), the JSON files if they name a command
- `specs/` — every spec: names and the `code:`/`tests:` frontmatter paths; `_overview.md` and `_index.md` (title "naoqi-bridge", the toolkit section, the planned `sim` backend: `NaoqiSimConfig`, `NaoqiSim.start()`, target id `"naoqi-sim"` detected by the `NaoqiSim` service); `project.md`; `testing.md`; `robot.md`; `bridge.md`; `ci.md`
- `plans/_index.md` — the intro's name and this plan's row
- `AGENTS.md` — the project map (`src/naoqi_bridge/*` rows, which `tests/test_project_map.py` checks), names; `README.md` — title "naoqi-bridge", install, the MCP client and WebSocket examples (`naoqi-mcp-server`, `naoqi-websocket-server`, `from naoqi_bridge import NaoqiBridge`)

Spec statuses: the spec edits land in the same change as the code, so every `Implemented` spec stays `Implemented`. If the spec edits are committed ahead of the code, set the touched specs to `Updated` until this plan is `Done`.

## Steps

1. **Local migration** (once for the four repositories, from a plain terminal, no Claude session open; analysis, "Local migration"): `gh repo rename naoqi-bridge`; `mv nao-bridge naoqi-bridge`; `git remote set-url origin git@github.com:funwithagents/naoqi-bridge.git`; move `~/.claude/projects/-Users-thibault-code-funwithagents-nao-bridge` to `…-naoqi-bridge` (after the backup) and rewrite the paths in it with the analysis's perl pass; `rm -rf .venv .pytest_cache .ruff_cache && uv sync --dev`; reopen VS Code and `claude` in the new folder, check `/resume` lists the old conversations.
2. Branch `rename-naoqi` (this repository's memory: no commits on `main`).
3. `git mv` the package, the two server modules, their tests and their specs.
4. Replace the tokens in the table, in that order, across tracked files except `plans/2*.md` (`git ls-files -z | xargs -0 perl -pi -e '…'`, one exact substitution per row). "Nao Bridge" is replaced by hand: it is prose, and "Nao" alone stays.
5. Review `git diff` for the kept names: `git grep -n -E 'Naoqi(Robot|State|Behavior)|RealNaoqi|FakeNaoqi|QiNaoqi|NAOQI_(IP|PORT|ALLOW_MOTION|INTERACTIVE)'` must return nothing.
6. `uv lock && rm -rf .venv && uv sync --dev`; lint, type check, tests (Verification).
7. MCP clients configured on this machine: none references `nao-mcp-server` today (checked Oct 12, 2026: Claude Desktop, Claude Code settings). Any tiny-agent folder made from the README needs its command changed to `naoqi-mcp-server`.
8. Commit, push, CI green; merge.
9. Claude memory in `~/.claude/projects/-Users-thibault-code-funwithagents-naoqi-bridge/memory/`: new names in `specs-self-contained.md`, `no-commits-on-main.md` and `MEMORY.md`. The naoqi-sim memory `libqi3-connect-flaky-retry.md` points at "nao-mcp" for the retry pattern: update it to `naoqi-bridge`'s `real_robot.py` (naoqi-sim's plan, step 11).

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` all clean (`tests/test_project_map.py` included).
- `git grep -n -E 'NaoBridge|nao_bridge|nao-bridge|Nao Bridge|NaoMcp|NaoWebsocket|nao_mcp|nao-mcp|nao_websocket|nao-websocket|NaoSim|nao-sim' -- ':!plans/2*'` returns nothing.
- `uv run python -c "from naoqi_bridge import NaoqiBridge"` works; `uv pip list` shows `naoqi-bridge` and no `nao_bridge`.
- `uv run naoqi-mcp-server --config examples/configs/mcp-fake.json` serves its tools to an MCP client; `uv run naoqi-websocket-server --config examples/configs/websocket-fake.json` accepts a client and reports its protocol version.
- With a robot or a running naoqi-sim at `NAO_IP`, `uv run pytest tests-e2e` passes its safe level.

Mark this plan `Done` here and in [_index.md](_index.md) once merged with CI green and the memories updated.

## Outcome (Oct 12, 2026)

Done as written, with these deviations:

- **No local migration here** (step 1): the GitHub repository was already renamed and `origin` already pointed to `funwithagents/naoqi-bridge`; the folder (`nao-bridge` → `naoqi-bridge`) and the Claude project folder move later, from a script.
- **Committed directly on `main`** (step 2 skipped, the user's rule for this repository), in one commit.
- Step 9 (Claude memory) is left to the user.
- Also renamed: the README's MCP client server key `"nao-mcp"` → `"naoqi-mcp"` (it was product-derived and caught by the verification grep).
- `uv run pytest tests-e2e` without a robot: 1 passed (no robot needed), 23 skipped. Both servers smoke-tested with the fake example configs (WebSocket: `NaoState` with `protocolVersion` 1; MCP: 19 tools listed).
