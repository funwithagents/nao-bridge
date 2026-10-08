"""The MCP server (specs/nao-mcp-server.md) on the ``fake`` backend, driven through
FastMCP's own tool registry the way an MCP client's calls arrive.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
import json
from typing import Any

from mcp.types import TextContent

from nao_bridge.nao_mcp_server import NaoMcpServer


async def call(server: NaoMcpServer, tool: str, **arguments: Any) -> str:
    result = await server.mcp.call_tool(tool, arguments)
    assert isinstance(result, tuple)
    content, _ = result
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


def test_tools_are_described_by_their_docstrings():
    async def run() -> dict[str, Any]:
        server = NaoMcpServer()
        return {tool.name: tool for tool in await server.mcp.list_tools()}

    tools = asyncio.run(run())
    assert set(tools) == {
        "set_tts_language",
        "say",
        "wake_up",
        "rest",
        "stand_up",
        "sit_down",
        "get_dance_list",
        "dance",
        "get_expressive_reaction_types",
        "expressive_reaction",
        "get_body_actions_list",
        "body_action",
        "get_app_list",
        "run_app",
        "stop_app",
    }
    assert tools["dance"].description.startswith("Make Nao perform a dance.")
    assert "get_dance_list" in tools["dance"].description
    assert tools["dance"].title is None


def test_action_tools_report_success_and_failure_as_text():
    async def run() -> list[str]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            return [
                await call(server, "say", text="Hello"),
                await call(server, "dance", dance_id="gangnam-style"),
                await call(server, "dance", dance_id="macarena"),
            ]

    assert asyncio.run(run()) == [
        "Nao said Hello",
        "Nao has danced the dance with id 'gangnam-style'",
        "Nao failed to dance the dance with id 'macarena'",
    ]


def test_list_tools_return_json_the_model_can_feed_back():
    async def run() -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            dances = json.loads(await call(server, "get_dance_list"))
            reactions = json.loads(await call(server, "get_expressive_reaction_types"))
            actions = json.loads(await call(server, "get_body_actions_list"))
            # An id read from the list is accepted by the matching action tool.
            assert await call(
                server, "body_action", body_action_id=actions[0]["id"]
            ) == (f"Nao has performed the body action with id '{actions[0]['id']}'")
        return dances, reactions, actions

    dances, reactions, actions = asyncio.run(run())
    assert len(dances) == 4
    assert set(dances[0]) == {"id", "behavior_name", "localized_name", "description"}
    assert set(dances[0]["localized_name"]) == {"en_US", "fr_FR"}
    assert reactions == ["Happy", "Proud", "Laugh", "Sad", "HeadTouched"]
    assert len(actions) == 6
