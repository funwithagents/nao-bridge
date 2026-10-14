"""Live: both servers over their real transports, on the target.

Safe level: the MCP server as a subprocess over stdio, driven by the `mcp` client the
way Claude Desktop drives it, so a stray libqi line on stdout would break the session;
on a sim, it connects to the run's sim. Motion level: the WebSocket server, whose
connect ritual wakes the robot and starts breathing, with every stream on.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import websockets
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from support import live_bridge_dict, live_config, require_motion

from naoqi_bridge import AudioStream, JointsStream, StreamSettings, TouchStream
from naoqi_bridge.naoqi_websocket_server import (
    NaoqiWebsocketServer,
    NaoqiWebsocketServerConfig,
    WebsocketServerSettings,
)

pytest.importorskip("qi")


def text_of(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


def test_the_mcp_server_drives_the_robot_over_stdio(tmp_path: Path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"bridge": live_bridge_dict()}))
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "naoqi_bridge.naoqi_mcp_server", "--config", str(path)],
    )

    async def run() -> tuple[set[str], list[Any], str]:
        async with (
            asyncio.timeout(60.0),
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            dances = json.loads(text_of(await session.call_tool("get_dance_list", {})))
            said = text_of(await session.call_tool("say", {"text": "Hello from MCP."}))
            return tools, dances, said

    tools, dances, said = asyncio.run(run())
    assert {"say", "dance", "stop_dance", "get_running"} <= tools
    assert isinstance(dances, list)
    assert said == "Nao said Hello from MCP."


def test_the_websocket_server_streams_the_robot_to_its_client():
    require_motion()
    config = NaoqiWebsocketServerConfig(
        bridge=live_config(
            StreamSettings(
                touch=TouchStream(enabled=True),
                joints=JointsStream(enabled=True, period_s=0.2),
                audio=AudioStream(enabled=True, channel="front"),
            )
        ),
        server=WebsocketServerSettings(host="127.0.0.1", port=0),
    )

    async def run() -> tuple[dict[str, Any], set[str], list[str]]:
        server = NaoqiWebsocketServer(config)
        assert await server.start_connection()
        try:
            address = server.address
            assert address is not None
            host, port = address
            async with websockets.connect(f"ws://{host}:{port}") as client:
                seen: dict[str, list[dict[str, Any]]] = {}

                async def until(message_id: str, count: int = 1) -> list[Any]:
                    async with asyncio.timeout(15.0):
                        while len(seen.get(message_id, [])) < count:
                            message = json.loads(await client.recv())
                            seen.setdefault(message["id"], []).append(message["data"])
                    return seen[message_id]

                state = (await until("NaoqiState"))[0]
                await until("Joints", 2)
                await until("Audio", 2)
                for uuid, command_id, data in [
                    ("c1", "ChangeEyesColor", {"color": "blue"}),
                    ("c2", "Say", {"text": "Hello from the WebSocket."}),
                ]:
                    await client.send(
                        json.dumps(
                            {
                                "id": "Command",
                                "data": {
                                    "commandUuid": uuid,
                                    "commandId": command_id,
                                    "commandData": data,
                                },
                            }
                        )
                    )
                ended = await until("CommandEnded", 2)
                results = [e["resultType"] for e in ended]
            return state, set(seen), results
        finally:
            await server.stop_connection()  # the disconnect ritual rests the robot

    state, kinds, results = asyncio.run(run())
    assert state["connected"] is True
    assert state["fakeRobot"] is False
    assert {"Joints", "Audio"} <= kinds
    assert results == ["Success", "Success"]
