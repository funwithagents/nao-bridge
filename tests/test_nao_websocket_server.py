"""The WebSocket server (specs/nao-websocket-server.md) on the ``fake`` backend: the
JSON protocol driven through the connection handler with an in-memory socket.

No robot or network needed. Async runs via ``asyncio.run``.
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import pytest

from nao_bridge.config import (
    AudioStream,
    JointsStream,
    NaoBridgeConfig,
    StreamSettings,
    TouchStream,
)
from nao_bridge.fake_robot import FakeNaoRobot
from nao_bridge.nao_websocket_server import NaoWebsocketServer, NaoWebsocketServerConfig

TOUCH_ONLY = NaoWebsocketServerConfig(
    bridge=NaoBridgeConfig(streams=StreamSettings(touch=TouchStream(enabled=True)))
)
ALL_STREAMS = NaoWebsocketServerConfig(
    bridge=NaoBridgeConfig(
        streams=StreamSettings(
            touch=TouchStream(enabled=True),
            joints=JointsStream(enabled=True, period_s=0.02),
            audio=AudioStream(enabled=True),
        )
    )
)


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class MemorySocket:
    """A client connection: yields ``incoming`` messages, then stays open until the
    server has answered ``answers`` commands and ``until`` holds; records what the
    server sends."""

    def __init__(
        self,
        incoming: Sequence[dict[str, Any] | str],
        answers: int = 0,
        until: Callable[["MemorySocket"], bool] = lambda _: True,
    ) -> None:
        self.incoming = incoming
        self.answers = answers
        self.until = until
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def of(self, message_id: str) -> list[dict[str, Any]]:
        return [m["data"] for m in self.sent if m["id"] == message_id]

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True

    async def _messages(self) -> AsyncIterator[str]:
        for message in self.incoming:
            yield message if isinstance(message, str) else json.dumps(message)
        await wait_until(
            lambda: len(self.of("CommandEnded")) >= self.answers and self.until(self)
        )

    def __aiter__(self) -> AsyncIterator[str]:
        return self._messages()


def command(uuid: str, command_id: str, **data: Any) -> dict[str, Any]:
    return {
        "id": "Command",
        "data": {"commandUuid": uuid, "commandId": command_id, "commandData": data},
    }


async def started_server(
    config: NaoWebsocketServerConfig = TOUCH_ONLY,
) -> tuple[NaoWebsocketServer, FakeNaoRobot]:
    """A server with its bridge up on the fake, without opening a network listener."""
    server = NaoWebsocketServer(config)
    server.async_loop = asyncio.get_running_loop()
    assert await server._start_bridge()
    robot = server.nao_bridge.robot
    assert isinstance(robot, FakeNaoRobot)
    return server, robot


def session(
    incoming: Sequence[dict[str, Any] | str], answers: int
) -> tuple[MemorySocket, list[str]]:
    socket = MemorySocket(incoming, answers)

    async def run() -> list[str]:
        server, robot = await started_server()
        await server._websocket_handler(socket)
        await server.nao_bridge.stop()
        return [name for name, _ in robot.commands]

    return socket, asyncio.run(run())


def test_a_client_session_readies_then_rests_the_robot():
    socket, robot_calls = session([], answers=0)
    assert socket.of("NaoState") == [{"connected": True, "fakeRobot": True}]
    assert robot_calls[robot_calls.index("fade_eyes") :][:3] == [
        "fade_eyes",
        "wake_up",
        "set_breathing",
    ]
    assert robot_calls[-5:] == [
        "fade_eyes",
        "set_breathing",
        "rest",
        "unsubscribe_touch",
        "close",
    ]
    assert socket.closed


def test_commands_answer_with_their_uuid_and_result():
    socket, robot_calls = session(
        [
            command("c1", "Say", text="Hello"),
            command("c2", "Dance", danceId="macarena"),
        ],
        answers=2,
    )
    results = {r["commandUuid"]: r["resultType"] for r in socket.of("CommandEnded")}
    assert results == {"c1": "Success", "c2": "Error"}
    assert "say" in robot_calls


def test_an_unknown_command_is_an_error_naming_it():
    socket, _ = session([command("c9", "Fly")], answers=1)
    [ended] = socket.of("CommandEnded")
    assert ended["resultType"] == "Error"
    assert "Fly" in ended["message"]
    assert set(ended) == {"commandUuid", "resultType", "message", "data"}


def test_bad_messages_are_reported_and_the_session_goes_on():
    socket, robot_calls = session(
        [
            "not json",
            {"id": "Telemetry", "data": {}},
            {"id": "Command", "data": {"commandId": "Say"}},  # no uuid / data
            command("c1", "Say", text="still here"),
        ],
        answers=1,
    )
    [ended] = socket.of("CommandEnded")
    assert (ended["commandUuid"], ended["resultType"]) == ("c1", "Success")
    assert "say" in robot_calls
    errors = [m for m in socket.of("Log") if m["logLevel"] == "ERROR"]
    assert len(errors) == 3


def test_a_second_client_replaces_the_first_one_cleanly(
    caplog: pytest.LogCaptureFixture,
):
    async def run() -> tuple[MemorySocket, MemorySocket, list[str]]:
        server, robot = await started_server()
        first = MemorySocket([], until=lambda s: s.closed)
        first_handler = asyncio.create_task(server._websocket_handler(first))
        await wait_until(lambda: server.websocket_client is first)
        robot.commands.clear()
        second = MemorySocket([])
        await server._websocket_handler(second)
        async with asyncio.timeout(2.0):
            await first_handler
        await server.nao_bridge.stop()
        return first, second, [name for name, _ in robot.commands]

    first, second, robot_calls = asyncio.run(run())
    assert first.closed and second.closed
    # The first client is reset (rest) before the second is readied (wake_up).
    assert robot_calls.index("rest") < robot_calls.index("wake_up")
    assert robot_calls.count("rest") == 2
    assert second.of("NaoState") == [{"connected": True, "fakeRobot": True}]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_catalog_commands_use_camel_case_payloads():
    socket, _ = session([command("c3", "GetBodyActionBehaviors")], answers=1)
    [ended] = socket.of("CommandEnded")
    assert ended["resultType"] == "Success"
    assert {
        "id": "UpLArm",
        "behaviorName": "dialog_move_arms/animations/UpLArm",
    }.items() <= next(a for a in ended["data"] if a["id"] == "UpLArm").items()
    assert set(ended["data"][0]) == {
        "id",
        "behaviorName",
        "localizedName",
        "description",
    }


def test_a_stop_command_ends_a_running_dance():
    async def run() -> MemorySocket:
        server, robot = await started_server()
        robot.behavior_duration_s = 5.0
        socket = MemorySocket(
            [command("d1", "Dance", danceId="eagle-dance")],
            answers=2,
        )
        handler = asyncio.create_task(server._websocket_handler(socket))
        await wait_until(lambda: "eagle-dance" in robot.running_behaviors)
        await server._command_callback(
            socket, command("d2", "StopDance", danceId="eagle-dance")["data"]
        )
        async with asyncio.timeout(2.0):
            await handler
        await server.nao_bridge.stop()
        return socket

    socket = asyncio.run(run())
    results = {r["commandUuid"]: r["resultType"] for r in socket.of("CommandEnded")}
    assert results == {"d1": "Success", "d2": "Success"}


def test_touch_events_are_streamed_to_the_client():
    async def run() -> MemorySocket:
        server, robot = await started_server()
        socket = MemorySocket([])
        server.websocket_client = socket
        robot.touch("MiddleTactilTouched", 1.0)
        await wait_until(lambda: bool(socket.of("Touch")))
        await server.nao_bridge.stop()
        return socket

    assert asyncio.run(run()).of("Touch") == [
        {"part": "MiddleTactilTouched", "touched": True}
    ]


def test_joints_and_audio_stream_to_the_client_during_its_session():
    async def run() -> tuple[MemorySocket, int]:
        server, robot = await started_server(ALL_STREAMS)
        robot.audio_chunk_s = 0.01
        socket = MemorySocket(
            [], until=lambda s: len(s.of("Joints")) >= 2 and len(s.of("Audio")) >= 3
        )
        await server._websocket_handler(socket)
        sent_at_close = len(socket.sent)
        await asyncio.sleep(0.1)  # the client is gone: its streams must have stopped
        late = len(socket.sent) - sent_at_close
        await server.nao_bridge.stop()
        return socket, late

    socket, late = asyncio.run(run())
    assert late == 0
    assert socket.of("Joints")[0] == {
        "jointsNames": ["HeadYaw", "HeadPitch"],
        "jointsAngles": [0.0, 0.1],
    }
    audio = socket.of("Audio")[-1]
    assert (audio["rate"], audio["channels"]) == (16000, 1)
    assert len(base64.b64decode(audio["data"])) == 2 * audio["nbSamplesPerChannel"]


def test_disabled_streams_send_nothing():
    socket, _ = session([command("c1", "WakeUp")], answers=1)
    assert socket.of("Joints") == [] and socket.of("Audio") == []
