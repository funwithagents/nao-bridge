# MCP stdout reserved for the protocol

**Status:** Done

Implements the edit to `specs/nao-mcp-server.md` ("stdout belongs to the protocol"), which resolves its open question 2. libqi's console log handler writes to file descriptor 1 natively; the first write comes from `qi.Session()` creation (`[W] … qi.path.sdklayout: No Application was created, trying to deduce paths`). Over the stdio transport, fd 1 is the JSON-RPC channel, so every `real` MCP run sends the client a non-JSON line ("Unexpected token" in Claude Desktop). It isn't caught by replacing `sys.stdout`, and `qi.logging` can only set levels and filters, not redirect the handler.

The fix: while serving over stdio, fd 1 points at stderr and the transport writes to a private duplicate of the real stdout. Any native writer (libqi now or later, another C library) lands on stderr; only JSON-RPC reaches the client. The bridge library itself never touches process file descriptors, so this lives in the MCP server.

## Scope

- `src/nao_bridge/nao_mcp_server.py` — a `stdout_reserved_for_protocol()` context manager, entered by `serve()` for the `stdio` transport *before* the bridge starts (the `qi.Session` is created in `start()`), and left after the bridge stops. It restores fd 1 and `sys.stdout`.
- `tests/test_nao_mcp_server.py`:
  - the guard in a subprocess: a native `os.write(1, …)` lands on stderr, and `sys.stdout` still reaches the real stdout;
  - the CLI on a `real` config at a closed local port, with `qi` installed: stdout stays empty;
  - the CLI on the fake answering `initialize`: stdout carries only JSON-RPC.
- `specs/nao-mcp-server.md` (→ `Updated` → `Implemented`), `specs/_index.md`, `README.md` (drop the "Unexpected token" warning).

## Steps

1. Spec: a "stdout belongs to the protocol" bullet; drop open question 2.
2. The context manager:
   - on entry, flush `sys.stdout`, `real_stdout_fd = os.dup(1)`, `os.dup2(2, 1)`, and set `sys.stdout = open(os.dup(real_stdout_fd), "w", encoding="utf-8")`. The transport gets a duplicate of its own, because it closes its stream when it ends;
   - on exit, flush and close the transport's stream if it's still open, restore the saved `sys.stdout`, then `os.dup2(real_stdout_fd, 1)` and close `real_stdout_fd`.
3. `serve()`: for `stdio`, `with stdout_reserved_for_protocol(): async with bridge: …`; `sse` is unchanged.
4. Tests, README, statuses.

## Verification

Done 2026-10-08:
- `test_libqi_logs_never_reach_the_mcp_client` failed before the fix (the libqi line on stdout) and passes after.
- The guard test and the fake JSON-RPC test pass, and 101 tests pass overall; ruff and pyright are clean.
- Manually: a `real` config leaves stdout empty, with the libqi warning on stderr; the fake answers `tools/list` and exits 0.
- A first version closed the real-stdout fd twice: the transport closes its stream when it ends, so the fake server exited with code 1. It was caught by the manual smoke run, fixed by giving the transport its own duplicate, and pinned by asserting exit code 0 in the fake test.
- Side finding, out of scope: an unreachable `robot.ip` costs about 76 s per connection attempt (the OS TCP timeout), so about 12 minutes with the default 10 tries. Recorded in the analysis notes.

The original checklist:

ruff, pyright and pytest all clean. Reproduce the bug before the fix with the new CLI test (it must fail), and see it pass after. `nao-mcp-server` on the fake still answers `tools/list`. The libqi warning now shows on stderr.
