# Example configs

Ready-to-use server configs (see [specs/config.md](../../specs/config.md)). Each file has a `bridge` block (a `NaoqiBridgeConfig`) and a `server` block (that server's own settings).

| File | Server | Robot | Streams |
|---|---|---|---|
| `mcp-fake.json` | `naoqi-mcp-server` | fake | none |
| `mcp-real.json` | `naoqi-mcp-server` | real (edit `robot.ip`) | none |
| `websocket-fake.json` | `naoqi-websocket-server` | fake | touch, joints, audio |
| `websocket-real.json` | `naoqi-websocket-server` | real (edit `robot.ip`) | touch, joints, audio |
| `mcp-sim.json` | `naoqi-mcp-server` | sim, NAOqi 2.1 | none |
| `websocket-sim.json` | `naoqi-websocket-server` | sim, NAOqi 2.1 | touch, joints, audio |

```bash
uv run naoqi-mcp-server --config examples/configs/mcp-fake.json
uv run naoqi-websocket-server --config examples/configs/websocket-real.json
```

To go from the robot to the fake, change `"backend"` to `"fake"`; the `robot` block can stay.

The `sim` files run a simulated Nao ([specs/sim.md](../../specs/sim.md)): they need the `naoqi-bridge[sim]` extra, Docker and, once per machine, `uv run naoqi-sim fetch-and-build-images`. `sim.config` is a naoqi-sim config as it is (here naoqi-sim's defaults on 2.1: the sim window, speech on the loudspeaker). With `"spawn": "auto"` the server starts the sim and stops it when it ends, or uses the one `naoqi-sim run` already runs and leaves it running. The sim has no touch input yet, so `on_touch` stays silent on it.
