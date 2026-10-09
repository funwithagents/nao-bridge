"""The MCP server (specs/nao-mcp-server.md) on the ``fake`` backend, driven through
FastMCP's own tool registry the way an MCP client's calls arrive.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
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


def test_action_tools_report_success_and_failure_with_its_reason():
    async def run() -> list[str]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            return [
                await call(server, "say", text="Hello"),
                await call(server, "dance", dance_id="gangnam-style"),
                await call(server, "dance", dance_id="macarena"),
                await call(server, "stop_app", app_id="follow-me"),
            ]

    said, danced, unknown, idle = asyncio.run(run())
    assert said == "Nao said Hello"
    assert danced == "Nao has danced the dance with id 'gangnam-style'"
    # The model reads why, and the ids it can use instead.
    assert unknown.startswith(
        "Nao failed to dance the dance with id 'macarena': "
        "unknown dance 'macarena' (known: caravan-palace-se, "
    )
    assert idle == (
        "Nao failed to stop the app with id 'follow-me': app 'follow-me' is not playing"
    )


def test_a_tool_on_a_stopped_bridge_says_it_is_not_running():
    result = asyncio.run(call(NaoMcpServer(), "wake_up"))
    assert result == (
        "Failed to enable Nao motors: the bridge is not running; call start() first"
    )


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


# --- stdout belongs to the protocol ------------------------------------------


def run_cli(
    config: dict[str, Any], tmp_path: Path, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return subprocess.run(
        [sys.executable, "-m", "nao_bridge.nao_mcp_server", "--config", str(path)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_native_writes_to_fd_1_go_to_stderr_while_reserved():
    script = (
        "import os, sys\n"
        "from nao_bridge.nao_mcp_server import stdout_reserved_for_protocol\n"
        "with stdout_reserved_for_protocol():\n"
        "    os.write(1, b'native\\n')\n"
        "    sys.stdout.write('protocol\\n')\n"
        "print('after')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "protocol\nafter\n"
    assert "native" in result.stderr


def test_libqi_logs_never_reach_the_mcp_client(tmp_path: Path):
    pytest.importorskip("qi")
    # A real backend at a closed local port: libqi creates its session (and logs
    # on its console handler), fails to connect, and the server exits.
    config = {
        "bridge": {
            "backend": "real",
            "robot": {"ip": "127.0.0.1", "port": 1, "connect_tries": 1},
        }
    }
    result = run_cli(config, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "qi.path.sdklayout" in result.stderr  # still visible, on stderr


def test_the_fake_server_writes_only_json_rpc_to_stdout(tmp_path: Path):
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    result = run_cli({}, tmp_path, stdin=json.dumps(initialize) + "\n")
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines
    assert all(json.loads(line)["jsonrpc"] == "2.0" for line in lines)
