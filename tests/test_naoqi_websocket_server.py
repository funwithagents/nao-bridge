"""The WebSocket server (specs/naoqi-websocket-server.md) on the ``fake`` backend: the
JSON protocol through ``ClientSession`` over an in-memory connection, and the
listener / single-client policy through ``NaoqiWebsocketServer`` on a loopback socket.

No robot or external network needed. Async runs via ``asyncio.run``.
"""

import asyncio
import base64
import io
import json
import logging
import socket as socket_module
import time
from collections.abc import AsyncIterator, Callable, Sequence
from types import SimpleNamespace
from typing import Any, Self

import pytest
import websockets
from PIL import Image

from naoqi_bridge import naoqi_websocket_server
from naoqi_bridge.bridge import NaoqiBridge
from naoqi_bridge.config import (
    AudioStream,
    CameraStream,
    CameraStreams,
    JointsStream,
    NaoqiBridgeConfig,
    StreamSettings,
)
from naoqi_bridge.fake_robot import (
    FAKE_CAMERA_TRANSFORMS,
    JOINT_NAMES,
    POSTURE_ANGLES,
    FakeNaoqiRobot,
)
from naoqi_bridge.naoqi_websocket_server import (
    ClientSession,
    NaoqiWebsocketServer,
    NaoqiWebsocketServerConfig,
    WebsocketServerSettings,
)

LOOPBACK = WebsocketServerSettings(host="127.0.0.1", port=0)
# The version is part of the contract: bumping it should take a test change too.
NAOQI_STATE = {"protocolVersion": 2, "connected": True, "fakeRobot": True}
TOUCH_ONLY = NaoqiWebsocketServerConfig(  # no stream switched on: touch is always on
    bridge=NaoqiBridgeConfig(),
    server=LOOPBACK,
)
ALL_STREAMS = NaoqiWebsocketServerConfig(
    bridge=NaoqiBridgeConfig(
        streams=StreamSettings(
            joints=JointsStream(enabled=True, period_s=0.02),
            audio=AudioStream(enabled=True),
        )
    ),
    server=LOOPBACK,
)


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class MemorySocket:
    """A client connection: yields ``incoming`` messages (and whatever ``push`` adds
    later), then stays open until the server has answered ``answers`` commands and
    ``until`` holds; records what the server sends."""

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
        self._later: asyncio.Queue[str] = asyncio.Queue()

    def push(self, message: dict[str, Any]) -> None:
        """Send ``message`` from the client, mid-session."""
        self._later.put_nowait(json.dumps(message))

    def of(self, message_id: str) -> list[dict[str, Any]]:
        return [m["data"] for m in self.sent if m["id"] == message_id]

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True

    async def _messages(self) -> AsyncIterator[str]:
        for message in self.incoming:
            yield message if isinstance(message, str) else json.dumps(message)
        async with asyncio.timeout(2.0):
            while not (
                len(self.of("CommandEnded")) >= self.answers and self.until(self)
            ):
                try:
                    yield await asyncio.wait_for(self._later.get(), 0.01)
                except TimeoutError:
                    pass

    def __aiter__(self) -> AsyncIterator[str]:
        return self._messages()


def command(uuid: str, command_id: str, **data: Any) -> dict[str, Any]:
    return {
        "id": "Command",
        "data": {"commandUuid": uuid, "commandId": command_id, "commandData": data},
    }


def fake(bridge: NaoqiBridge) -> FakeNaoqiRobot:
    robot = bridge.robot
    assert isinstance(robot, FakeNaoqiRobot)
    return robot


def session(
    incoming: Sequence[dict[str, Any] | str],
    answers: int,
    config: NaoqiWebsocketServerConfig = TOUCH_ONLY,
) -> tuple[MemorySocket, list[str]]:
    """Serve one in-memory client over a started bridge; the robot calls it made."""
    socket = MemorySocket(incoming, answers)

    async def run() -> list[str]:
        async with NaoqiBridge(config.bridge) as bridge:
            robot = fake(bridge)
            await ClientSession(bridge, config, socket).serve()
        return [name for name, _ in robot.commands]

    return socket, asyncio.run(run())


# --- the protocol, over an in-memory connection -------------------------------


def test_a_client_session_readies_then_rests_the_robot():
    socket, robot_calls = session([], answers=0)
    assert socket.of("NaoqiState") == [NAOQI_STATE]
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
    ended = {r["commandUuid"]: r for r in socket.of("CommandEnded")}
    assert (ended["c1"]["resultType"], ended["c1"]["message"]) == ("Success", "")
    assert ended["c2"]["resultType"] == "Error"
    assert ended["c2"]["message"].startswith(
        "unknown dance 'macarena' (known: caravan-palace-se, "
    )
    assert "say" in robot_calls


def test_a_failed_ritual_step_is_a_warning_and_the_session_goes_on(
    monkeypatch: pytest.MonkeyPatch,
):
    def broken_wake_up(self: FakeNaoqiRobot) -> None:
        raise RuntimeError("motors too hot")

    monkeypatch.setattr(FakeNaoqiRobot, "wake_up", broken_wake_up)
    socket, robot_calls = session([command("c1", "Say", text="Hello")], answers=1)
    [ended] = socket.of("CommandEnded")
    assert ended["resultType"] == "Success"
    assert {
        "log": "Session ritual step skipped: wake_up failed: motors too hot",
        "logLevel": "WARNING",
    } in socket.of("Log")
    # The steps after the failed one still ran: breathing on, refused with the motors
    # off, then the whole disconnect ritual.
    assert {
        "log": "Session ritual step skipped: set_breathing_enabled: the motors are "
        "off; call wake_up() first",
        "logLevel": "WARNING",
    } in socket.of("Log")
    assert robot_calls.count("set_breathing") == 1
    assert robot_calls[-3:] == ["rest", "unsubscribe_touch", "close"]


def test_every_command_result_carries_the_four_keys():
    socket, _ = session(
        [command("c9", "Fly"), command("c8", "Say")],  # unknown; missing `text`
        answers=2,
    )
    ended = {r["commandUuid"]: r for r in socket.of("CommandEnded")}
    assert all(
        set(r) == {"commandUuid", "resultType", "message", "data"}
        for r in ended.values()
    )
    assert ended["c9"]["resultType"] == "Error" and "Fly" in ended["c9"]["message"]
    assert ended["c8"]["resultType"] == "Error" and "text" in ended["c8"]["message"]


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
        async with NaoqiBridge(TOUCH_ONLY.bridge) as bridge:
            robot = fake(bridge)
            robot.behavior_duration_s = 5.0
            socket = MemorySocket(
                [command("d1", "Dance", danceId="eagle-dance")],
                answers=2,
            )
            serving = asyncio.create_task(
                ClientSession(bridge, TOUCH_ONLY, socket).serve()
            )
            await wait_until(lambda: "eagle-dance" in robot.running_behaviors)
            socket.push(command("d2", "StopDance", danceId="eagle-dance"))
            async with asyncio.timeout(2.0):
                await serving
        return socket

    socket = asyncio.run(run())
    results = {r["commandUuid"]: r["resultType"] for r in socket.of("CommandEnded")}
    assert results == {"d1": "Success", "d2": "Success"}


def test_touch_events_are_streamed_only_during_the_session():
    async def run() -> tuple[MemorySocket, int]:
        async with NaoqiBridge(TOUCH_ONLY.bridge) as bridge:
            robot = fake(bridge)
            socket = MemorySocket([], until=lambda s: bool(s.of("Touch")))
            serving = asyncio.create_task(
                ClientSession(bridge, TOUCH_ONLY, socket).serve()
            )
            await wait_until(lambda: bool(socket.of("NaoqiState")))
            robot.touch("MiddleTactilTouched", 1.0)
            async with asyncio.timeout(2.0):
                await serving
            robot.touch("MiddleTactilTouched", 0.0)  # the client is gone
            await asyncio.sleep(0.05)
        return socket, len(socket.of("Touch"))

    socket, touches = asyncio.run(run())
    assert socket.of("Touch") == [{"part": "MiddleTactilTouched", "touched": True}]
    assert touches == 1


def test_a_session_closed_while_opening_streams_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    wake_up = FakeNaoqiRobot.wake_up

    def slow_wake_up(self: FakeNaoqiRobot) -> None:
        time.sleep(0.3)  # the opening ritual is still going when the session closes
        wake_up(self)

    async def run() -> MemorySocket:
        monkeypatch.setattr(FakeNaoqiRobot, "wake_up", slow_wake_up)
        async with NaoqiBridge(TOUCH_ONLY.bridge) as bridge:
            socket = MemorySocket([], until=lambda s: s.closed)
            session = ClientSession(bridge, TOUCH_ONLY, socket)
            serving = asyncio.create_task(session.serve())
            await asyncio.sleep(0.1)
            await session.close()
            async with asyncio.timeout(2.0):
                await serving
            fake(bridge).touch("MiddleTactilTouched", 1.0)  # after the session
            await asyncio.sleep(0.05)
        return socket

    socket = asyncio.run(run())
    assert socket.closed
    assert socket.of("Touch") == []


def test_joints_and_audio_stream_to_the_client_during_its_session():
    async def run() -> tuple[MemorySocket, int]:
        async with NaoqiBridge(ALL_STREAMS.bridge) as bridge:
            fake(bridge).audio_chunk_s = 0.01
            socket = MemorySocket(
                [],
                until=lambda s: len(s.of("Joints")) >= 2 and len(s.of("Audio")) >= 3,
            )
            await ClientSession(bridge, ALL_STREAMS, socket).serve()
            sent_at_close = len(socket.sent)
            await asyncio.sleep(
                0.1
            )  # the client is gone: its streams must have stopped
            late = len(socket.sent) - sent_at_close
        return socket, late

    socket, late = asyncio.run(run())
    assert late == 0
    assert socket.of("Joints")[0] == {
        "jointsNames": list(JOINT_NAMES),
        "jointsAngles": list(POSTURE_ANGLES["Crouch"]),
    }
    audio = socket.of("Audio")[-1]
    assert (audio["rate"], audio["channels"]) == (16000, 1)
    assert len(base64.b64decode(audio["data"])) == 2 * audio["nbSamplesPerChannel"]


def test_disabled_streams_send_nothing():
    socket, _ = session([command("c1", "WakeUp")], answers=1)
    assert socket.of("Joints") == [] and socket.of("Audio") == []
    assert socket.of("Frame") == []


def test_frames_of_the_enabled_camera_stream_as_jpeg_during_the_session():
    config = NaoqiWebsocketServerConfig(
        bridge=NaoqiBridgeConfig(
            streams=StreamSettings(
                cameras=CameraStreams(
                    top=CameraStream(enabled=True, resolution="qvga", fps=30)
                )
            )
        ),
        server=LOOPBACK,
    )

    async def run() -> tuple[MemorySocket, int, int]:
        async with NaoqiBridge(config.bridge) as bridge:
            socket = MemorySocket([], until=lambda s: len(s.of("Frame")) >= 3)
            await ClientSession(bridge, config, socket).serve()
            sent_at_close = len(socket.sent)
            await asyncio.sleep(0.1)  # the client is gone: its frames must stop
            late = len(socket.sent) - sent_at_close
            published = bridge.cameras["top"].published_count
        return socket, late, published

    socket, late, published = asyncio.run(run())
    assert late == 0
    frames = socket.of("Frame")
    assert {f["camera"] for f in frames} == {"top"}  # the bottom camera is off
    ids = [f["frameId"] for f in frames]
    assert ids == sorted(set(ids)) and ids[-1] <= published  # each frame once
    frame = frames[-1]
    assert (frame["width"], frame["height"], frame["format"]) == (320, 240, "jpeg")
    image = Image.open(io.BytesIO(base64.b64decode(frame["data"])))
    assert (image.format, image.size) == ("JPEG", (320, 240))
    # The fake's blue ramp survives the BGR -> JPEG trip: blue on the right edge.
    red, _, blue = image.convert("RGB").getpixel((315, 120))  # type: ignore[misc]
    assert blue > 200 and red < 50
    assert frame["cameraTransform"] == list(FAKE_CAMERA_TRANSFORMS["top"])
    assert len(frame["fov"]) == 2


# --- the server: listener and single-client policy ----------------------------


def test_a_second_client_replaces_the_first_one_cleanly(
    caplog: pytest.LogCaptureFixture,
):
    async def run() -> tuple[MemorySocket, MemorySocket, list[str]]:
        server = NaoqiWebsocketServer(TOUCH_ONLY)
        assert await server.start_connection()
        robot = fake(server.naoqi_bridge)
        first = MemorySocket([], until=lambda s: s.closed)
        first_serving = asyncio.create_task(server.attach(first))
        await wait_until(lambda: bool(first.of("NaoqiState")))
        robot.commands.clear()
        second = MemorySocket([])
        await server.attach(second)
        async with asyncio.timeout(2.0):
            await first_serving
        await server.stop_connection()
        return first, second, [name for name, _ in robot.commands]

    first, second, robot_calls = asyncio.run(run())
    assert first.closed and second.closed
    # The first client is reset (rest) before the second is readied (wake_up).
    assert robot_calls.index("rest") < robot_calls.index("wake_up")
    assert robot_calls.count("rest") == 2
    assert second.of("NaoqiState") == [NAOQI_STATE]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_the_listener_serves_a_real_websocket_client_on_the_configured_host():
    async def run() -> tuple[tuple[str, int] | None, dict[str, Any], dict[str, Any]]:
        server = NaoqiWebsocketServer(TOUCH_ONLY)
        assert await server.start_connection()
        address = server.address
        assert address is not None
        host, port = address
        async with websockets.connect(f"ws://{host}:{port}") as client:

            async def receive(message_id: str) -> dict[str, Any]:
                async with asyncio.timeout(2.0):
                    while True:  # Log lines are interleaved with everything else
                        message = json.loads(await client.recv())
                        if message["id"] == message_id:
                            return message["data"]

            state = await receive("NaoqiState")
            await client.send(json.dumps(command("c1", "Say", text="over the wire")))
            ended = await receive("CommandEnded")
        await wait_until(lambda: server.session is None)
        await server.stop_connection()
        return address, state, ended

    address, state, ended = asyncio.run(run())
    assert address is not None and address[0] == "127.0.0.1" and address[1] > 0
    assert state == NAOQI_STATE
    assert (ended["commandUuid"], ended["resultType"]) == ("c1", "Success")


def test_stopping_the_server_ends_the_client_and_the_bridge():
    async def run() -> tuple[bool, bool, bool]:
        server = NaoqiWebsocketServer(TOUCH_ONLY)
        assert await server.start_connection()
        socket = MemorySocket([], until=lambda s: s.closed)
        serving = asyncio.create_task(server.attach(socket))
        await wait_until(lambda: server.session is not None)
        await server.stop_connection()
        async with asyncio.timeout(2.0):
            await serving
        return socket.closed, server.address is None, server.naoqi_bridge.running

    assert asyncio.run(run()) == (True, True, False)


def test_an_unreachable_robot_is_reported_not_raised():
    config = NaoqiWebsocketServerConfig(
        bridge=NaoqiBridgeConfig.from_dict(
            {
                "backend": "real",
                "robot": {"ip": "127.0.0.1", "port": 1},
            }
        ),
        server=LOOPBACK,
    )
    pytest.importorskip("qi")
    server = NaoqiWebsocketServer(config)
    assert asyncio.run(server.start_connection()) is False
    assert server.address is None


class _NoRouteSocket:
    """A UDP socket whose ``connect`` fails, as with no network."""

    def __init__(self, *args: object) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def connect(self, address: object) -> None:
        raise OSError(51, "Network is unreachable")


def test_with_no_route_out_an_empty_host_listens_on_loopback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # Only the server module's view of ``socket`` is offline; websockets binds as usual.
    offline = SimpleNamespace(
        socket=_NoRouteSocket,
        AF_INET=socket_module.AF_INET,
        SOCK_DGRAM=socket_module.SOCK_DGRAM,
    )
    monkeypatch.setattr(naoqi_websocket_server, "socket", offline)

    async def run() -> tuple[str, int] | None:
        server = NaoqiWebsocketServer(
            NaoqiWebsocketServerConfig(server=WebsocketServerSettings(port=0))
        )
        assert await server.start_connection()
        address = server.address
        await server.stop_connection()
        return address

    with caplog.at_level(logging.WARNING, logger="naoqi_bridge.naoqi_websocket_server"):
        address = asyncio.run(run())
    assert address is not None and address[0] == "127.0.0.1"
    assert any("listening on 127.0.0.1 only" in m for m in caplog.messages)


def test_a_port_already_in_use_fails_the_start_and_stops_the_bridge(
    caplog: pytest.LogCaptureFixture,
):
    with socket_module.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        server = NaoqiWebsocketServer(
            NaoqiWebsocketServerConfig(
                server=WebsocketServerSettings(host="127.0.0.1", port=port)
            )
        )
        with caplog.at_level(
            logging.ERROR, logger="naoqi_bridge.naoqi_websocket_server"
        ):
            started = asyncio.run(server.start_connection())
    assert started is False
    assert server.address is None
    assert not server.naoqi_bridge.running
    assert any(f"Could not listen on 127.0.0.1:{port}" in m for m in caplog.messages)
