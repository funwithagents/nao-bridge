---
code:
  - src/naoqi_bridge/viewer.py
  - src/naoqi_bridge/config.py
  - src/naoqi_bridge/bridge.py
  - src/naoqi_bridge/errors.py
  - src/naoqi_bridge/naoqi_mcp_server.py
  - src/naoqi_bridge/naoqi_websocket_server.py
  - pyproject.toml
  - examples/configs/mcp-real.json
  - examples/configs/websocket-real.json
tests:
  - tests/test_viewer.py
  - tests/test_config.py
  - tests-e2e/test_live_viewer.py
---

# The viewer

**Status:** Implemented

## Purpose

A window showing the robot the bridge drives, posed live: the NAO model in [naoqi-viewer](https://github.com/funwithagents/naoqi-viewer)'s **mirror** mode, which reads joint angles and the torso pose from a Naoqi over qi and renders them. The viewer only reads; it never commands the robot. It lets a developer watch what an agent makes a Nao do, on a robot across the room or a headless sim, and, with naoqi-viewer's ghost, see the commanded pose next to the measured one.

naoqi-viewer is a separate package: it owns the NAO MuJoCo model, the license-gated meshes, the window and the viewer process. The bridge only builds a `NaoqiViewer` from its config, launches it with the session and closes it with the session. naoqi-sim already drives naoqi-viewer in its **sim** mode, for the sim window and the render camera ([sim.md](sim.md)); the bridge's viewer is a different use of the same package and never uses sim mode.

## Decided

### Config: the `viewer` block

```json
{
  "backend": "real",
  "robot": { "ip": "192.168.1.42" },
  "viewer": {
    "enabled": true,
    "config": { "ghost": true, "world": { "variant": "auto" } }
  }
}
```

```python
@dataclass
class ViewerSettings:
    enabled: bool = False                     # open the viewer at start() (below, "Which robot it mirrors")
    config: NaoqiViewerConfig | None = None   # naoqi-viewer's own config, minus what the bridge sets; None: its defaults
```

- `enabled` is the switch, as the streams' are: a config keeps its viewer settings while the window is off.
- `config` is a naoqi-viewer `NaoqiViewerConfig` block ([naoqi-viewer's config](https://github.com/funwithagents/naoqi-viewer/blob/main/specs/config.md)): `naoqi.rate_hz`, `world.scene`, `world.variant`, `ghost` and `launch_timeout_s` pass through with naoqi-viewer's rules and defaults.
- **Three fields follow from the bridge, so they are not settings.** `mode` is always `mirror` (the bridge needs no camera renders, sim mode is naoqi-sim's), `headless` always `false` (a headless mirror shows nothing, naoqi-viewer rejects it) and `naoqi.url` is the robot the bridge connects to (below). Any of them in `viewer.config` is a `ConfigError` on its key, saying the bridge sets it: `viewer.config.naoqi.url is set by the bridge (the robot it connects to)`.
- `config` goes to naoqi-viewer's `NaoqiViewerConfig.from_dict`, imported lazily from `naoqi_viewer.config` (standard library only: no `mujoco`, no `qi`). Its `ConfigError` is re-raised as ours with `viewer.config.` in front, as `sim.config`'s is ([config.md](config.md)).
- **Without naoqi-viewer installed** (neither `[viewer]` nor `[sim]`), `viewer.enabled: true` on `real` or `sim` is a `ConfigError` on `viewer.enabled` naming `naoqi-bridge[viewer]`. On `fake`, or with `enabled: false`, `viewer.config` is accepted unchecked and `config` stays `None`, so a file that switches backends still loads on a platform without the extra.
- A relative `world.scene` path resolves against the working directory, not the bridge's config file: the bridge hands naoqi-viewer a dict (the same limit as `sim.config`'s paths, [sim.md](sim.md) open question 3).

### Which robot it mirrors

At `start()`, with `viewer.enabled`, the backend and the sim's lease decide whether the viewer opens, and on what:

| Backend | Viewer | Why |
|---|---|---|
| `real` | Mirror on `tcp://<robot.ip>:<robot.port>` | The main use: watching a robot |
| `sim`, a sim the bridge borrowed | Mirror on the lease's URL | A borrowed sim may run headless (the live tier's, a `naoqi-sim run`); the bridge can't know whether it shows a window, so it opens its own |
| `sim`, a sim the bridge started, headless (`sim.config.viewer.headless: true`) | Mirror on the lease's URL | The sim has no window; the bridge's is the only one |
| `sim`, a sim the bridge started, with its window (`sim.config.viewer.headless: false`, naoqi-sim's default) | **Not opened**, logged at `WARNING` | The sim's own window already shows this robot; a second one would mirror the same pose |
| `fake` | **Not opened**, logged at `WARNING` | The viewer reads a Naoqi over qi, and the fake has none |

- The two skips are warnings, not errors: the config asked for something the bridge won't do, and the session is otherwise fine. Each message says why and what to change: `viewer.enabled is ignored on the fake backend: the viewer mirrors a Naoqi over qi` and `viewer not opened: the sim this bridge started shows its own window; set sim.config.viewer.headless to true to use the bridge's viewer instead`.
- Skipping, not refusing at load, keeps a config's backend a one-word switch: a `real` config with the viewer on still runs on `fake` and on `sim` unchanged ([config.md](config.md)).

### NAOqi versions

The viewer's qi calls (`ALMotion.getAngles`, `getTransform`) are the same on 2.1 and 2.8, so it mirrors both. Its model is NAO V5 geometry, checked against NAOqi 2.1 within 0.03 mm and 0.03°; on a 2.8 Naoqi (a V6 robot, a 2.8 sim) it runs, with fidelity naoqi-viewer hasn't measured yet. The bridge neither checks nor warns about the version; that's naoqi-viewer's open question.

### In the bridge's lifecycle

- **`start()`** opens the viewer **last**, once the robot is connected, the streams subscribed and the catalog loaded, so a session that fails never flashes a window. `NaoqiViewer.launch()` blocks until the window has drawn its first frame (up to `launch_timeout_s`, 30 s by default) and runs in `asyncio.to_thread`. If it fails, everything already started is torn down (the robot closed, the sim released) and `start()` raises `ViewerError`. A cancel while it launches waits for the launch in its thread (bounded by `launch_timeout_s`), closes the viewer, then tears down as for any cancelled `start()` ([bridge.md](bridge.md), "Cancellation").
- **`stop()`** closes the viewer **first**, before the robot, so the window never shows a disconnected robot. `NaoqiViewer.close()` sends `stop`, waits up to 5 s, then terminates the viewer process; it runs in `asyncio.to_thread` and is harmless if the window is already gone.
- **The user closing the window** ends the viewer, not the session: the bridge keeps running and doesn't reopen it. The next `start()` after a `stop()` opens a new one.
- **The window never outlives the bridge's process**: naoqi-viewer ties the viewer process to its control connection, so a crashed or killed server takes its window with it.
- The viewer process's logs reach the `naoqi_viewer.viewer_process` logger, so the CLIs' logging shows them without setup. Its stdout is a pipe naoqi-viewer reads, never the process's fd 1, so the MCP server's stdio transport is untouched.
- On macOS a window needs `mjpython`, which `launch()` picks from the environment (it comes with `mujoco`). A machine with no display (a server, CI) can't open one: that's a `ViewerError` from `start()`.

### Errors

| What failed | What the caller gets |
|---|---|
| `viewer.enabled` on `real` or `sim` without naoqi-viewer | `ConfigError` at load, key `viewer.enabled`, naming `naoqi-bridge[viewer]` |
| `mode`, `headless` or `naoqi.url` in `viewer.config`; anything naoqi-viewer's loader rejects | `ConfigError` at load, key under `viewer.config.` |
| The viewer can't launch: no display, no `mjpython`, a missing scene file, `variant: "aldebaran"` without the meshes, a timeout (naoqi-viewer's `LaunchError`) | `ViewerError(BridgeError)` from `start()`, with naoqi-viewer's message (which says what to do), chained |

`ViewerError` lives in `errors.py` and is re-exported from the front door. The servers' CLIs exit 1 on it, as on an unreachable robot: the session they were asked for can't start ([config.md](config.md), "CLIs").

### `viewer.py`

`src/naoqi_bridge/viewer.py` is the one module that imports `naoqi_viewer` beyond its config, and only inside its functions, as `sim.py` is for naoqi-sim. It holds the decision table above and the launch and close:

```python
def viewer_target(config: NaoqiBridgeConfig, lease: SimLease | None) -> str | None: ...
    # the Naoqi URL to mirror, or None after logging why it's skipped

async def open_viewer(settings: ViewerSettings, url: str) -> NaoqiViewer: ...
    # NaoqiViewerConfig with mode/headless/url set, launched off the loop; LaunchError → ViewerError

async def close_viewer(viewer: NaoqiViewer) -> None: ...
```

The bridge holds the `NaoqiViewer` for the session and exposes nothing of it: the viewer is for a person watching, not for the bridge's callers.

### Installing it: the `[viewer]` extra

- `naoqi-bridge[viewer]` adds `naoqi-viewer`, with `qi`'s platform marker (naoqi-viewer needs `qi`), so the viewer exists on macOS arm64, Linux x86_64 and Windows x64, as `real` does.
- naoqi-viewer is not on PyPI: `[tool.uv.sources]` takes it from `https://github.com/funwithagents/naoqi-viewer`, pinned to a commit. **That pin is naoqi-sim's**: `[sim]` already installs naoqi-viewer through `naoqi-sim[viewer]`, at the commit naoqi-sim pins, and one environment holds one naoqi-viewer. The two pins move together: bumping naoqi-sim means setting naoqi-viewer to the commit naoqi-sim now pins ([project.md](project.md)).
- `[sim]` alone is enough for the viewer (it brings naoqi-viewer); `[viewer]` is for a `real` setup that doesn't want naoqi-sim.
- Aldebaran's meshes are naoqi-viewer's: `uv run naoqi-viewer fetch-meshes` once per machine, after its license prompt, for `variant: "aldebaran"` (or `auto`, which uses them when installed). The bridge never runs it.

### Testing

- **Fast tier**: the config rules above (the three refused fields, the `viewer.config.` prefix, the missing-extra rule per backend); `viewer_target` over the decision table, the two warnings included; the lifecycle against a stub `NaoqiViewer` replacing naoqi-viewer's: launched after the robot connects and with the URL the table gives, closed before the robot on `stop()`, a `LaunchError` turned into `ViewerError` with the robot closed and the sim released, a cancelled launch closed.
- **Live tier**: a window needs a display, so it's opt-in and local, never in CI. With `NAOQI_E2E_VIEWER=1` ([testing.md](testing.md)), a test starts a bridge with the viewer on the target (the session's sim, borrowed, or the robot): `start()` returns with the window up, and after `stop()` the viewer process is gone. Whether the pose is right is naoqi-viewer's own live tier.

### Example files

`mcp-real.json` and `websocket-real.json` gain `"viewer": { "enabled": false, "config": { "ghost": true } }`: the window is one switch away, and a server started from Claude Desktop doesn't open one unasked.

## Open questions

1. **A viewer on the fake.** naoqi-viewer reads only over qi, so the fake can't be mirrored. A naoqi-viewer pose source fed by the bridge (`bridge.joints`) would let the fake show a moving robot; it's a naoqi-viewer change first.
2. **Reopening.** A closed window stays closed for the session. A bridge method (or an MCP tool) to reopen it is deferred until someone misses it.
3. **Several windows per sim.** A borrowed sim that already shows its window gets a second one from the bridge; naoqi-sim's status service doesn't say whether its window is open. Revisit if it bothers anyone.
