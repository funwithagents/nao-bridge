# Example configs

Ready-to-use server configs (see [specs/config.md](../../specs/config.md)). Each file has a `bridge` block (a `NaoBridgeConfig`) and a `server` block (that server's own settings).

| File | Server | Robot | Streams |
|---|---|---|---|
| `mcp-fake.json` | `nao-mcp-server` | fake | none |
| `mcp-real.json` | `nao-mcp-server` | real (edit `robot.ip`) | none |
| `websocket-fake.json` | `nao-websocket-server` | fake | touch, joints, audio |
| `websocket-real.json` | `nao-websocket-server` | real (edit `robot.ip`) | touch, joints, audio |

```bash
uv run nao-mcp-server --config examples/configs/mcp-fake.json
uv run nao-websocket-server --config examples/configs/websocket-real.json
```

To go from the robot to the fake, change `"backend"` to `"fake"`; the `robot` block can stay.
