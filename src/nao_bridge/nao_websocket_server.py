"""Nao WebSocket server: a single-client JSON protocol over ``NaoBridge``.

Specified by [specs/nao-websocket-server.md](../../specs/nao-websocket-server.md).
Two objects: ``ClientSession`` is the protocol over one connection-like object
(commands in, results and the robot's touch / joints / audio / log events out), and
``NaoWebsocketServer`` owns the bridge and the listener, serving one session at a
time, built from a ``NaoWebsocketServerConfig``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, Self

import websockets
from websockets.asyncio.server import Server, ServerConnection

from .bridge import BehaviorInfos, NaoBridge, TouchEvent
from .config import (
    ConfigError,
    JsonConfig,
    NaoBridgeConfig,
    as_int,
    as_str,
    parse_block,
)
from .errors import BridgeError
from .robot import RobotConnectionError

__all__ = [
    "ClientSession",
    "Connection",
    "NaoWebsocketServer",
    "NaoWebsocketServerConfig",
    "WebsocketServerSettings",
]

logger = logging.getLogger(__name__)

# A command's ``commandData`` object.
type CommandData = dict[str, Any]
# A verb: runs the command, raising why it failed. A query: answers with a payload.
type Verb = Callable[[CommandData], Awaitable[None]]
type Query = Callable[[], Any]


@dataclass(frozen=True)
class WebsocketServerSettings(JsonConfig):
    """The WebSocket server's own settings: the ``server`` block.

    ``host`` is the address to bind; empty means the machine's LAN IP, found at
    start. ``port`` 0 lets the OS pick a free port.
    """

    host: str = ""
    port: int = 8002

    def __post_init__(self) -> None:
        if not 0 <= self.port < 65536:
            raise ConfigError(
                f"must be between 0 and 65535, got {self.port}", key="port"
            )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(cls, data, path, host=as_str, port=as_int)


@dataclass(frozen=True)
class NaoWebsocketServerConfig(JsonConfig):
    """``{"bridge": NaoBridgeConfig, "server": WebsocketServerSettings}``; both optional."""

    bridge: NaoBridgeConfig = field(default_factory=NaoBridgeConfig)
    server: WebsocketServerSettings = field(default_factory=WebsocketServerSettings)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls,
            data,
            path,
            bridge=NaoBridgeConfig.parse,
            server=WebsocketServerSettings.parse,
        )


class Connection(Protocol):
    """What a session needs from a client connection: incoming text messages,
    ``send`` and ``close``. A ``websockets`` connection is one; so is an in-memory
    stand-in in a test."""

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...
    async def send(self, message: str) -> None: ...
    async def close(self) -> None: ...


def _behavior_payload(behavior: BehaviorInfos) -> dict[str, Any]:
    """A ``BehaviorInfos`` as the protocol's camelCase object."""
    return {
        "id": behavior.id,
        "behaviorName": behavior.behavior_name,
        "localizedName": asdict(behavior.localized_name),
        "description": behavior.description,
    }


class ClientSession:
    """The protocol over one connection, for as long as it lasts.

    ``serve()`` readies the robot, sends ``NaoState``, starts the streams the bridge
    config enables, then reads commands until the connection ends; ``close()`` ends
    the session from the server's side (a newer client, shutdown). Every command runs
    as its own task, so a long one (``Dance``) doesn't block its stop command.
    """

    def __init__(
        self,
        bridge: NaoBridge,
        config: NaoWebsocketServerConfig,
        connection: Connection,
    ) -> None:
        self._bridge = bridge
        self._config = config
        self._connection = connection
        self._closing = False
        self._closed = False
        # Strong references so running tasks aren't garbage-collected mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()
        self._stream_tasks: set[asyncio.Task[None]] = set()

        b = bridge
        self._verbs: dict[str, Verb] = {
            "GenericNao": self._generic,
            "SetTTSLanguage": lambda d: b.set_tts_language(str(d["language"])),
            "Say": lambda d: b.say(str(d["text"])),
            "StopSay": lambda d: b.stop_say(),
            "WakeUp": lambda d: b.wake_up(),
            "Rest": lambda d: b.rest(),
            "StandUp": lambda d: b.stand_up(),
            "SitDown": lambda d: b.sit_down(),
            "ChangeEyesColor": lambda d: b.change_eyes_color(str(d["color"])),
            "Dance": lambda d: b.dance(str(d["danceId"])),
            "StopDance": lambda d: b.stop_dance(str(d["danceId"])),
            "ExpressiveReaction": lambda d: b.expressive_reaction(
                str(d["reactionType"])
            ),
            "StopExpressiveReaction": lambda d: b.stop_expressive_reaction(
                str(d["reactionType"])
            ),
            "BodyAction": lambda d: b.body_action(str(d["bodyActionId"])),
            "StopBodyAction": lambda d: b.stop_body_action(str(d["bodyActionId"])),
            "RunApp": lambda d: b.run_app(str(d["appId"])),
            "StopApp": lambda d: b.stop_app(str(d["appId"])),
            "SetBasicAwarenessState": lambda d: b.set_basic_awareness_state(
                bool(d["enabled"]), str(d["engagementMode"]), str(d["trackingMode"])
            ),
            "SetBreathingEnabled": lambda d: b.set_breathing_enabled(
                bool(d["enabled"]), str(d["chainName"])
            ),
            "RunBehavior": lambda d: b.run_behavior(str(d["name"])),
            "StopBehavior": lambda d: b.stop_behavior(str(d["name"])),
        }
        self._queries: dict[str, Query] = {
            "GetDanceBehaviors": lambda: [
                _behavior_payload(x) for x in b.get_dance_behaviors()
            ],
            "GetExpressiveReactionTypes": b.get_expressive_reaction_types,
            "GetBodyActionBehaviors": lambda: [
                _behavior_payload(x) for x in b.get_body_action_behaviors()
            ],
            "GetAppBehaviors": lambda: [
                _behavior_payload(x) for x in b.get_app_behaviors()
            ],
        }

    @property
    def closed(self) -> bool:
        return self._closed

    # --- lifecycle ---

    async def serve(self) -> None:
        """Run the session until the connection ends (or ``close()`` is called)."""
        await self._open()
        try:
            async for raw in self._connection:
                await self._receive(raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        """End the session: stop its streams, reset the robot, close the connection.
        A no-op once done, so the server and ``serve()`` can both call it."""
        if self._closing:
            return
        self._closing = True
        await self._stop_streams()
        if self._config.bridge.streams.touch.enabled:
            self._bridge.on_touch.unsubscribe(self._on_touch)
        self._log(logging.INFO, "Reset Nao state after disconnection")
        await self._ritual_step(self._bridge.change_eyes_color("white"))
        await self._ritual_step(self._bridge.set_breathing_enabled(False, "Body"))
        await self._ritual_step(self._bridge.rest())
        await self._connection.close()
        self._closed = True

    async def _open(self) -> None:
        self._log(logging.INFO, "Init Nao state after connection")
        await self._ritual_step(self._bridge.change_eyes_color("cyan"))
        await self._ritual_step(self._bridge.wake_up())
        await self._ritual_step(self._bridge.set_breathing_enabled(True, "Body"))
        await self._send(
            "NaoState",
            {
                "connected": self._bridge.running,
                "fakeRobot": self._bridge.backend == "fake",
            },
        )
        streams = self._config.bridge.streams
        if streams.touch.enabled:
            self._bridge.on_touch.subscribe(self._on_touch)
        if streams.joints.enabled:
            self._spawn(self._stream_joints(), self._stream_tasks)
        if streams.audio.enabled:
            self._spawn(self._stream_audio(), self._stream_tasks)

    async def _ritual_step(self, step: Awaitable[None]) -> None:
        """One step of the connect / disconnect ritual: a failure is a warning, and
        the ritual goes on."""
        try:
            await step
        except BridgeError as e:
            self._log(logging.WARNING, f"Session ritual step skipped: {e}")

    def _spawn(
        self, coro: Coroutine[Any, Any, None], tasks: set[asyncio.Task[None]]
    ) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def _stop_streams(self) -> None:
        tasks = list(self._stream_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- outgoing ---

    async def _send(self, message_id: str, data: Any) -> None:
        if self._closing:
            return
        try:
            await self._connection.send(json.dumps({"id": message_id, "data": data}))
        except websockets.ConnectionClosed:
            pass
        except Exception:
            logger.exception("failed to send a %s message", message_id)

    def _log(self, level: int, message: str) -> None:
        """Log, and mirror the line to the client as a ``Log`` message."""
        logger.log(level, message)
        if not self._closing:
            self._spawn(
                self._send(
                    "Log", {"log": message, "logLevel": logging.getLevelName(level)}
                ),
                self._tasks,
            )

    # --- streams ---

    def _on_touch(self, event: TouchEvent) -> None:
        """``bridge.on_touch`` handler, on the event loop: forward as a Touch message."""
        self._log(
            logging.INFO,
            f"Touch detected with key = {event.part}, touched = {event.touched}",
        )
        self._spawn(
            self._send("Touch", {"part": event.part, "touched": event.touched}),
            self._tasks,
        )

    async def _stream_joints(self) -> None:
        async for state in self._bridge.joints.changes():
            if state is None:
                continue
            await self._send(
                "Joints",
                {"jointsNames": list(state.names), "jointsAngles": list(state.angles)},
            )

    async def _stream_audio(self) -> None:
        mic = self._bridge.mic
        async for chunk in self._bridge.audio_input():
            await self._send(
                "Audio",
                {
                    "rate": mic.sample_rate,
                    "channels": mic.channels,
                    "nbSamplesPerChannel": len(chunk) // (2 * mic.channels),
                    "data": base64.b64encode(chunk).decode("ascii"),
                },
            )

    # --- incoming ---

    async def _receive(self, raw: str | bytes) -> None:
        """Dispatch one incoming message; a bad one is reported, never fatal."""
        logger.info("Received message: %s", raw)
        try:
            message = json.loads(raw)
            message_id = message["id"]
            if message_id != "Command":
                raise ValueError(f"unknown message id {message_id!r}")
            payload = message["data"]
            command_uuid = str(payload["commandUuid"])
            command_id = str(payload["commandId"])
            command_data = payload["commandData"]
        except Exception as e:  # noqa: BLE001 - reported to the client, never fatal
            self._log(logging.ERROR, f"Bad message ignored: {e!r}")
            return
        self._spawn(
            self._run_command(command_uuid, command_id, command_data), self._tasks
        )

    async def _run_command(
        self, command_uuid: str, command_id: str, command_data: CommandData
    ) -> None:
        self._log(
            logging.INFO, f"applying command '{command_id}' with data = {command_data}"
        )
        result, data, message = False, None, ""
        try:
            if command_id in self._verbs:
                await self._verbs[command_id](command_data)
                result = True
            elif command_id in self._queries:
                result, data = True, self._queries[command_id]()
            else:
                message = f"command not found: {command_id}"
        except (BridgeError, ValueError) as e:  # a verb's own reason
            message = str(e)
        except Exception as e:  # noqa: BLE001 - reported to the client as an Error result
            message = f"error in command '{command_id}': {e!r}"
        if message:
            self._log(logging.ERROR, message)
        self._log(
            logging.INFO,
            f"command '{command_id}' ended: {'Success' if result else 'Error'}",
        )
        await self._send(
            "CommandEnded",
            {
                "commandUuid": command_uuid,
                "resultType": "Success" if result else "Error",
                "message": message,
                "data": data,
            },
        )

    async def _generic(self, command_data: CommandData) -> None:
        self._log(logging.INFO, f"text = {command_data['text']}")


def _lan_ip() -> str:
    """The address of the interface that routes out, via a UDP socket (no packet)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


class NaoWebsocketServer:
    """The bridge plus a WebSocket listener serving one ``ClientSession`` at a time.

    ``start_connection()`` starts the bridge and listens; ``stop_connection()``
    undoes both. ``attach(connection)`` is what the listener calls for each accepted
    connection, and a host with its own transport can call it too.
    """

    def __init__(self, config: NaoWebsocketServerConfig | None = None) -> None:
        self.config = config or NaoWebsocketServerConfig()
        self.nao_bridge = NaoBridge(self.config.bridge)
        self._server: Server | None = None
        self._session: ClientSession | None = None

    @property
    def address(self) -> tuple[str, int] | None:
        """The ``(host, port)`` the listener is bound to; ``None`` while not serving."""
        if self._server is None:
            return None
        host, port = self._server.sockets[0].getsockname()[:2]
        return str(host), int(port)

    @property
    def session(self) -> ClientSession | None:
        """The client being served, if any."""
        return self._session

    async def start_connection(self) -> bool:
        """Start the bridge and listen; ``False`` if the robot is unreachable."""
        logger.info("Starting nao connection")
        try:
            await self.nao_bridge.start()
        except RobotConnectionError as e:
            logger.error("Could not connect to Nao: %s", e)
            return False
        settings = self.config.server
        host = settings.host or _lan_ip()
        self._server = await websockets.serve(self.attach, host, settings.port)
        logger.info("WebSocket server listening on %s:%d", *(self.address or (host, 0)))
        return True

    async def stop_connection(self) -> None:
        """End the client's session, close the listener, stop the bridge."""
        logger.info("Stopping nao connection")
        if self._session is not None:
            await self._session.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self.nao_bridge.stop()

    async def attach(self, connection: Connection | ServerConnection) -> None:
        """Serve ``connection`` as the client until it ends, replacing the current one."""
        if self._session is not None:
            logger.info(
                "Received connection from another client, disconnecting previous one"
            )
            await self._session.close()
        session = ClientSession(self.nao_bridge, self.config, connection)
        self._session = session
        try:
            await session.serve()
        finally:
            if self._session is session:
                self._session = None


async def _main(config: NaoWebsocketServerConfig) -> None:
    server = NaoWebsocketServer(config)
    if not await server.start_connection():
        logger.error("failed to connect to Nao, exiting")
        raise SystemExit(1)
    await asyncio.to_thread(input, "Press Enter to end...\n")
    logger.info("Ending received")
    await server.stop_connection()


def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="Nao WebSocket Server")
    parser.add_argument(
        "--config",
        help="Path to a JSON server config (default: the fake robot on port 8002)",
    )
    args = parser.parse_args()
    try:
        config = (
            NaoWebsocketServerConfig.from_json_file(args.config)
            if args.config
            else NaoWebsocketServerConfig()
        )
    except ConfigError as e:
        parser.error(str(e))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(_main(config))


if __name__ == "__main__":
    main()
