"""The MCP server (specs/nao-mcp-server.md) on the ``fake`` backend, driven through
FastMCP's own tool registry the way an MCP client's calls arrive.

No robot needed. Async runs via ``asyncio.run``.
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from mcp.types import TextContent

from nao_bridge.fake_robot import FakeNaoRobot
from nao_bridge.nao_mcp_server import NaoMcpServer


async def call(server: NaoMcpServer, tool: str, **arguments: Any) -> str:
    result = await server.mcp.call_tool(tool, arguments)
    assert isinstance(result, tuple)
    content, _ = result
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


def fake(server: NaoMcpServer) -> FakeNaoRobot:
    robot = server.nao_bridge.robot
    assert isinstance(robot, FakeNaoRobot)
    return robot


async def running(server: NaoMcpServer) -> dict[str, list[str]]:
    return json.loads(await call(server, "get_running"))


async def wait_until_idle(server: NaoMcpServer, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while any((await running(server)).values()):
            await asyncio.sleep(0.01)


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
        "stop_dance",
        "get_expressive_reaction_types",
        "expressive_reaction",
        "stop_expressive_reaction",
        "get_body_actions_list",
        "body_action",
        "stop_body_action",
        "get_app_list",
        "run_app",
        "stop_app",
        "get_running",
    }
    assert tools["dance"].description.startswith("Make Nao start a dance.")
    assert "get_dance_list" in tools["dance"].description
    assert "stop_dance" in tools["dance"].description
    assert tools["dance"].title is None


def test_action_tools_report_success_and_failure_with_its_reason():
    async def run() -> list[str]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            asleep = await call(server, "dance", dance_id="gangnam-style")
            await call(server, "wake_up")
            return [
                asleep,
                await call(server, "say", text="Hello"),
                await call(server, "dance", dance_id="gangnam-style"),
                await call(server, "dance", dance_id="macarena"),
                await call(server, "stop_app", app_id="follow-me"),
            ]

    asleep, said, danced, unknown, idle = asyncio.run(run())
    assert asleep == (
        "Nao failed to dance the dance with id 'gangnam-style': "
        "dance: the motors are off; call wake_up() first"
    )
    assert said == "Nao said Hello"
    assert danced == "Nao started dancing the dance with id 'gangnam-style'"
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
            await call(server, "wake_up")
            actions = json.loads(await call(server, "get_body_actions_list"))
            # An id read from the list is accepted by the matching action tool.
            assert await call(
                server, "body_action", body_action_id=actions[0]["id"]
            ) == (f"Nao started the body action with id '{actions[0]['id']}'")
        return dances, reactions, actions

    dances, reactions, actions = asyncio.run(run())
    assert len(dances) == 4
    assert set(dances[0]) == {"id", "behavior_name", "localized_name", "description"}
    assert set(dances[0]["localized_name"]) == {"en_US", "fr_FR"}
    assert reactions == ["Happy", "Proud", "Laugh", "Sad", "HeadTouched"]
    assert len(actions) == 6


# --- Behaviors return once started --------------------------------------------


def test_a_dance_returns_while_it_plays_and_stop_dance_ends_it():
    async def run() -> tuple[str, float, dict[str, list[str]], str, list[str]]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            await call(server, "wake_up")
            fake(server).behavior_duration_s = 5.0
            started = time.monotonic()
            result = await call(server, "dance", dance_id="eagle-dance")
            elapsed = time.monotonic() - started
            playing = await running(server)
            stopped = await call(server, "stop_dance", dance_id="eagle-dance")
            await wait_until_idle(server)
            return result, elapsed, playing, stopped, fake(server).running_behaviors

    result, elapsed, playing, stopped, still_running = asyncio.run(run())
    assert result == "Nao started dancing the dance with id 'eagle-dance'"
    assert elapsed < 1.0  # not held for the dance's 5 s
    assert playing == {
        "dances": ["eagle-dance"],
        "expressive_reactions": [],
        "body_actions": [],
        "apps": [],
    }
    assert stopped == "Nao has stopped the dance with id 'eagle-dance'"
    assert still_running == []


def test_reactions_and_body_actions_start_and_stop_through_their_tools():
    async def run() -> tuple[list[str], dict[str, list[str]], list[str]]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            await call(server, "wake_up")
            fake(server).behavior_duration_s = 5.0
            started = [
                await call(server, "expressive_reaction", reaction_type="Happy"),
                await call(server, "body_action", body_action_id="UpLArm"),
                await call(server, "run_app", app_id="follow-me"),
            ]
            playing = await running(server)
            stopped = [
                await call(server, "stop_expressive_reaction", reaction_type="Happy"),
                await call(server, "stop_body_action", body_action_id="UpLArm"),
                await call(server, "stop_app", app_id="follow-me"),
            ]
            await wait_until_idle(server)
            return started, playing, stopped

    started, playing, stopped = asyncio.run(run())
    assert started == [
        "Nao started reacting for type 'Happy'",
        "Nao started the body action with id 'UpLArm'",
        "Nao started the app with id 'follow-me'",
    ]
    assert playing == {
        "dances": [],
        "expressive_reactions": ["Happy"],
        "body_actions": ["UpLArm"],
        "apps": ["follow-me"],
    }
    assert stopped == [
        "Nao has stopped reacting for type 'Happy'",
        "Nao has stopped the body action with id 'UpLArm'",
        "Nao has stopped the app with id 'follow-me'",
    ]


def test_stop_tools_say_when_nothing_is_playing():
    async def run() -> list[str]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            return [
                await call(server, "stop_dance", dance_id="eagle-dance"),
                await call(server, "stop_expressive_reaction", reaction_type="Sad"),
                await call(server, "stop_body_action", body_action_id="macarena"),
            ]

    idle, sad, unknown = asyncio.run(run())
    assert idle == (
        "Nao failed to stop the dance with id 'eagle-dance': "
        "dance 'eagle-dance' is not playing"
    )
    assert sad == (
        "Nao failed to stop reacting for type 'Sad': reaction type 'Sad' is not playing"
    )
    assert unknown.startswith(
        "Nao failed to stop the body action with id 'macarena': "
        "unknown body action 'macarena' (known: "
    )


def test_a_behavior_failing_after_it_started_is_logged(
    caplog: pytest.LogCaptureFixture,
):
    def failing_run(name: str) -> None:
        time.sleep(0.1)
        raise RuntimeError(f"{name} fell over")

    async def run() -> tuple[str, dict[str, list[str]]]:
        server = NaoMcpServer()
        async with server.nao_bridge:
            await call(server, "wake_up")
            fake(server).run_behavior = failing_run
            result = await call(server, "dance", dance_id="eagle-dance")
            await wait_until_idle(server)
            return result, await running(server)

    with caplog.at_level(logging.ERROR, logger="nao_bridge.nao_mcp_server"):
        result, after = asyncio.run(run())
    assert result == "Nao started dancing the dance with id 'eagle-dance'"
    assert after["dances"] == []
    assert (
        "Nao failed to dance the dance with id 'eagle-dance': "
        "run_behavior failed: eagle-dance fell over"
    ) in caplog.messages


def test_leaving_serve_cancels_the_behaviors_still_running():
    async def run() -> tuple[str, float, bool, list[str]]:
        server = NaoMcpServer()
        results: list[str] = []
        robots: list[FakeNaoRobot] = []

        async def client_session() -> None:
            await call(server, "wake_up")
            robots.append(fake(server))
            robots[0].behavior_duration_s = 5.0
            results.append(await call(server, "run_app", app_id="follow-me"))

        started = time.monotonic()
        await server._serve(client_session)  # pyright: ignore[reportPrivateUsage]
        elapsed = time.monotonic() - started
        left = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return (
            results[0],
            elapsed,
            server.nao_bridge.running or bool(left),
            robots[0].running_behaviors,
        )

    result, elapsed, still_serving, still_running = asyncio.run(run())
    assert result == "Nao started the app with id 'follow-me'"
    assert elapsed < 1.0  # the app's 5 s didn't hold the shutdown
    assert not still_serving
    assert still_running == []


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
