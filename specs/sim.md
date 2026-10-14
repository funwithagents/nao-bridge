---
code:
  - src/naoqi_bridge/sim.py
  - src/naoqi_bridge/config.py
  - src/naoqi_bridge/bridge.py
  - src/naoqi_bridge/robot.py
  - src/naoqi_bridge/sim_robot.py
tests:
  - tests/test_sim.py
  - tests/test_sim_robot.py
  - tests/test_config.py
  - tests/test_bridge.py
  - tests-e2e/test_live_sim.py
---

# The `sim` backend

**Status:** Implemented

## Purpose

A third backend, next to `real` and `fake`: a simulated Nao from [naoqi-sim](https://github.com/funwithagents/naoqi-sim), NAOqi itself in a local Docker container, reached over `qi` like a robot. It gives the bridge a real Naoqi without hardware, so that:

- a developer runs the bridge, both servers and an agent against a Nao that speaks, moves and hears, on their machine, from one config file;
- the live tier ([testing.md](testing.md)) runs on a headless sim locally and in CI ([ci.md](ci.md)), not only on a robot someone holds.

naoqi-sim already serves any qi client at `tcp://127.0.0.1:9559`, so a sim was reachable before as `real` at `127.0.0.1`. The backend adds what that left to the user: **starting and stopping the sim with the bridge**, from the config, and knowing that the target is naoqi-sim of the version asked for. Once connected, the verbs, the catalog and the streams run through the same `RealNaoqiRobot` as on a robot. The one exception is sitting on a 2.8 sim (below, "What a sim offers the bridge"), a workaround for a limit of Aldebaran's 2.8 desktop suite that naoqi-sim documents.

## Decided

### What `sim` means

`{"backend": "sim", "sim": {"spawn": …, "config": {…}}}` ([config.md](config.md)). The `sim` block holds the bridge's own `spawn` and, under `config`, a naoqi-sim `NaoqiSimConfig` (`naoqi`, `speech`, `audio_output`, `audio_input`, `video_input`, `viewer`):

```json
{
  "backend": "sim",
  "sim": {
    "spawn": "auto",
    "config": {
      "naoqi": { "version": "2.1" },
      "viewer": { "headless": true },
      "audio_output": { "mode": "silent" }
    }
  }
}
```

- The robot is a `SimNaoqiRobot` ([robot.md](robot.md)): a `RealNaoqiRobot` at `127.0.0.1:9559`, naoqi-sim's fixed address, one sim per machine. It knows nothing of the sim's lifecycle, which is the bridge's (below). `robot.ip` and `robot.port` are validated but not applied, as the `robot` block on `fake`.
- naoqi-sim owns everything about the sim (Docker, the images, the containers, the host devices, the viewer); the bridge only calls its public API (`NaoqiSim`, `read_status`) and never `docker` itself.
- `sim.config` is a naoqi-sim config file as it is: one pastes in, and copies back out to `naoqi-sim run --config`, unchanged.

### Own it or borrow it: `sim.spawn`

| `spawn` | A ready naoqi-sim already runs on this machine | None runs |
|---|---|---|
| `auto` (default) | **Borrow** it | **Start** one and own it |
| `always` | `RobotConnectionError`: the config asked for a sim of its own | **Start** one and own it |
| `never` | **Borrow** it | `RobotConnectionError`: start one with `naoqi-sim run`, or set `spawn` to `auto` |

- **Which sim runs** is naoqi-sim's `read_status()`: its NAOqi container is healthy and its `NaoqiSim` service answers. A sim whose containers exist but aren't healthy yet (booting) is waited for, up to `sim.config.naoqi.ready_timeout_s`, then borrowed; one that doesn't get there is a `RobotConnectionError`.
- **A borrowed sim must be the version asked for.** Its `NaoqiSim` service reports its NAOqi version (`2.1.4.13`, `2.8.7.4`); one that isn't `sim.config.naoqi.version` is a `RobotConnectionError` naming both. The bridge never drives another version than the config says, as it never falls back to the fake.
- **A borrowed sim runs as it was started.** The device settings of `sim.config` (`speech`, `audio_*`, `video_input`, `viewer`) apply only to a sim the bridge starts. Whoever started a borrowed one (`naoqi-sim run` in another terminal, the live tier's fixture, another bridge) stops it.
- **An owned sim** is `NaoqiSim(sim.config)`, whose `start()` checks Docker, the images and the ports, starts the containers and waits until NAOqi is ready ([naoqi-sim's API](https://github.com/funwithagents/naoqi-sim/blob/main/specs/runtime/api.md)). `start()` never builds images: missing or outdated ones fail with naoqi-sim's message, which names `naoqi-sim fetch-and-build-images`. The bridge stops it in `stop()`.
- Something else on port 9559 that isn't naoqi-sim (a Choregraphe virtual robot) is not a sim: `auto` and `always` fail on naoqi-sim's port check, `never` finds no sim.

### `sim.py`: the lease

The own-or-borrow decision lives in its own module, `src/naoqi_bridge/sim.py`, the one module that imports `naoqi_sim`, and only inside its functions.

```python
@dataclass
class SimLease:
    url: str          # "tcp://127.0.0.1:9559"
    owned: bool       # True when this lease started the sim; release() then stops it
    naoqi_version: str

    @property
    def sim(self) -> NaoqiSim | None: ...  # the NaoqiSim this lease started; None when borrowed or released

    async def release(self) -> None: ...   # stops an owned sim; a no-op on a borrowed one


async def acquire_sim(settings: SimSettings) -> SimLease: ...
```

- `acquire_sim` applies the table above. Its blocking work (`read_status`, the boot wait) runs in naoqi-sim's own threads; `NaoqiSim.start()` is already async.
- **Cancel-safe**: a cancelled `acquire_sim` stops a sim it was starting before re-raising (naoqi-sim's `start()` does it, [naoqi-sim's API](https://github.com/funwithagents/naoqi-sim/blob/main/specs/runtime/api.md) "Lifecycle"), and gives up a boot wait at its next poll (1 s).
- `release()` of an owned sim is `NaoqiSim.stop()`: the containers go down (seconds), the package store volumes stay.
- **`sim`** is naoqi-sim's own object, for its own API: the fake microphone a test plays into, and the devices to come (touch). naoqi-sim keeps that API in the process that started the sim, so only an owned lease has it. The bridge's lease is its own; the live tier's session fixture holds one directly ([testing.md](testing.md), "Live tier: the target").

### In the bridge's lifecycle

- **`start()`** on `sim` acquires the lease first, then builds and connects the robot as on `real`, subscribes the streams and loads the catalog. If a later step fails or `start()` is cancelled, the robot is closed and the lease released before the error propagates ([bridge.md](bridge.md), "Construction and lifecycle").
- **`stop()`** closes the robot, then releases the lease, last; owned once begun, like the rest of `stop()`. Stopping a bridge that owns its sim takes the few seconds of `docker compose down`.
- **The bridge's viewer** ([viewer.md](viewer.md)) mirrors a borrowed sim, or one it started headless; a sim it started with its own window is not mirrored twice (a warning says so).
- `bridge.backend` is `"sim"`. The WebSocket server's `NaoqiState.fakeRobot` is `false` on it, as on `real`.

### Errors

| What failed | What the caller gets |
|---|---|
| `backend: "sim"` without the `[sim]` extra | `ConfigError` at load, key `backend`, naming `naoqi-bridge[sim]` |
| No sim to borrow (`never`), one already running (`always`), the wrong version, a boot that never got healthy | `RobotConnectionError` from `start()`, saying which |
| naoqi-sim can't start one: Docker, images, a port, a boot (`NaoqiSimError` and its subclasses) | `RobotConnectionError` from `start()`, with naoqi-sim's message (it says what to do), chained to naoqi-sim's error |

So an unavailable sim is what an unreachable robot is: `start()` raises `RobotConnectionError`, and the servers' CLIs exit 1 on it as they do for a robot ([config.md](config.md), "CLIs").

### Installing it: the `[sim]` extra

- `naoqi-bridge[sim]` adds `naoqi-sim[viewer]`, from naoqi-sim's GitHub repository pinned to a commit in `[tool.uv.sources]` ([project.md](project.md)). The viewer extra comes with it, so `"viewer": {"headless": false}` opens the sim window and the render camera works; whether the viewer runs at all stays naoqi-sim's rule (a window, or a headless viewer only with `video_input.source: "render"`).
- The extra carries the platform marker of `qi`: naoqi-sim needs `qi`, so `sim` exists on macOS arm64, Linux x86_64 and Windows x64 only, as `real`.
- Once per machine, `uv run naoqi-sim fetch-and-build-images` builds the images (the one slow step; Docker and Aldebaran's public suite downloads). The bridge never runs it.
- Without the extra, `naoqi_bridge` and every other backend work as before; `config.py` and the bridge import nothing from naoqi-sim at module level.

### What a sim offers the bridge

The sim is a desktop NAOqi with naoqi-sim's replacements; from the bridge's side:

| | On a sim |
|---|---|
| Speech, language, postures, motors, breathing, eyes, basic awareness | As on a robot (speech through naoqi-sim's `ALTextToSpeech` replacement) |
| Joints | NAOqi's own model of the body |
| Audio stream | naoqi-sim's `ALAudioDevice` replacement: its audio input's source (`fake`, `mic`), or none |
| Touch | Not yet: naoqi-sim's touch input is not built |
| Catalog | The `animations` package only: no dances, no apps, no body actions; reactions from what `animations` holds |
| NAOqi 2.8 | Runs; the bridge is verified on 2.1 only, so 2.8 is where `RealNaoqiRobot`'s 2.8 gaps show first |
| Sit, on 2.8 | The 2.8 desktop suite has no DCM, so its robot has no inertial sensor: `ALRobotPosture` takes the lean of Stand → Sit for a push and stays standing, and from Crouch it reaches Sit but often reports it didn't (naoqi-sim's known issue). So on a 2.8 sim `RealNaoqiRobot` sits through Crouch and judges the move by `getPosture()` ([robot.md](robot.md), "`SimNaoqiRobot`"): `sit_down` works, in 15 to 25 s. Everywhere else, Sit is asked for directly |

### Example files

`examples/configs/mcp-sim.json` and `websocket-sim.json`: the `sim` backend on 2.1 with naoqi-sim's defaults (the sim window, speech on the loudspeaker), `spawn: "auto"`, so a user who already runs `naoqi-sim run` gets it borrowed.

## Open questions

1. **Touch on the sim.** naoqi-sim plans `sim.touch(...)` for tests; once it exists, the live tier's touch test can press the head itself on a sim instead of skipping.
2. **Packages on the sim.** Dances, apps and body actions need packages the sim doesn't have (Aldebaran's are the user's own). A test package the live tier installs into the sim would let their tests run there.
3. **Paths in `sim.config`** (`audio_output.record`, a scene file) resolve against the working directory, not the bridge's config file: the bridge hands naoqi-sim a dict. Revisit if someone records from a server config.
4. **Several sims per machine** wait for naoqi-sim's configurable ports.
