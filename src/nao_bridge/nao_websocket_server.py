"""Nao WebSocket Server Module.

A single-client JSON WebSocket server over NaoBridge: commands in, results and live
robot events (touch, joints, audio, logs) out. Specified by
[specs/nao-websocket-server.md](../../specs/nao-websocket-server.md).
"""

import argparse
import asyncio
import base64
import json
import logging
import socket
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import Any, Self

import websockets

from .bridge import BehaviorInfos, NaoBridge, TouchEvent
from .config import (
    ConfigError,
    JsonConfig,
    NaoBridgeConfig,
    build,
    check_keys,
    key_path,
    read_int,
    read_object,
)
from .robot import RobotConnectionError

logger = logging.getLogger(__name__)

type CommandHandler = Callable[[Any], Awaitable[tuple[bool, Any]]]


@dataclass(frozen=True)
class WebsocketServerSettings(JsonConfig):
    """The WebSocket server's own settings: the ``server`` block."""

    port: int = 8002

    def __post_init__(self) -> None:
        if not 0 < self.port < 65536:
            raise ConfigError(f"port must be between 1 and 65535, got {self.port}")

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("port",), path)
        return build(cls, path, port=read_int(obj, "port", 8002, path))


@dataclass(frozen=True)
class NaoWebsocketServerConfig(JsonConfig):
    """``{"bridge": NaoBridgeConfig, "server": WebsocketServerSettings}``; both optional."""

    bridge: NaoBridgeConfig = field(default_factory=NaoBridgeConfig)
    server: WebsocketServerSettings = field(default_factory=WebsocketServerSettings)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("bridge", "server"), path)
        return build(
            cls,
            path,
            bridge=NaoBridgeConfig.parse(
                obj.get("bridge", {}), key_path(path, "bridge")
            ),
            server=WebsocketServerSettings.parse(
                obj.get("server", {}), key_path(path, "server")
            ),
        )


class NaoWebsocketServer:
    def __init__(self, config: NaoWebsocketServerConfig | None = None):
        """Build the server and its bridge from ``config`` (default: the fake robot)."""
        self.config = config or NaoWebsocketServerConfig()
        self.backend = self.config.bridge.backend
        self.websocket_port = self.config.server.port

        self.ip_self = ""
        self.async_loop: asyncio.AbstractEventLoop | None = None

        self.websocket_server: Any = None
        self.websocket_server_event = asyncio.Event()
        self.websocket_stop_event = asyncio.Event()
        self.websocket_running = False
        self.websocket_client: Any = None
        self.websocket_closing = False

        self.nao_bridge = NaoBridge(self.config.bridge)
        self.nao_connected = False
        # Strong references so running tasks aren't garbage-collected mid-flight.
        self._command_tasks: set[asyncio.Task[None]] = set()
        self._send_tasks: set[asyncio.Task[None]] = set()
        # The current client's joints / audio streams, cancelled when it leaves.
        self._stream_tasks: set[asyncio.Task[None]] = set()

        self.command_mapping = dict[str, CommandHandler]()
        self.command_mapping["GenericNao"] = self._apply_command_generic
        self.command_mapping["SetTTSLanguage"] = self._apply_command_set_tts_language
        self.command_mapping["Say"] = self._apply_command_say
        self.command_mapping["StopSay"] = self._apply_command_stop_say
        self.command_mapping["WakeUp"] = self._apply_command_wake_up
        self.command_mapping["Rest"] = self._apply_command_rest
        self.command_mapping["StandUp"] = self._apply_command_stand_up
        self.command_mapping["SitDown"] = self._apply_command_sit_down
        self.command_mapping["ChangeEyesColor"] = self._apply_command_change_eyes_color
        self.command_mapping["GetDanceBehaviors"] = (
            self._apply_command_get_dance_behaviors
        )
        self.command_mapping["Dance"] = self._apply_command_dance
        self.command_mapping["StopDance"] = self._apply_command_stop_dance
        self.command_mapping["GetExpressiveReactionTypes"] = (
            self._apply_command_get_expressive_reaction_types
        )
        self.command_mapping["ExpressiveReaction"] = (
            self._apply_command_expressive_reaction
        )
        self.command_mapping["StopExpressiveReaction"] = (
            self._apply_command_stop_expressive_reaction
        )
        self.command_mapping["GetBodyActionBehaviors"] = (
            self._apply_command_get_body_action_behaviors
        )
        self.command_mapping["BodyAction"] = self._apply_command_body_action
        self.command_mapping["StopBodyAction"] = self._apply_command_stop_body_action
        self.command_mapping["GetAppBehaviors"] = self._apply_command_get_app_behaviors
        self.command_mapping["RunApp"] = self._apply_command_run_app
        self.command_mapping["StopApp"] = self._apply_command_stop_app

        self.command_mapping["SetBasicAwarenessState"] = (
            self._apply_command_set_basic_awareness_state
        )
        self.command_mapping["SetBreathingEnabled"] = (
            self._apply_command_set_breathing_enabled
        )
        self.command_mapping["RunBehavior"] = self._apply_command_runbehavior
        self.command_mapping["StopBehavior"] = self._apply_command_stopbehavior

    # region Connection management
    async def start_connection(self) -> bool:
        self.async_loop = asyncio.get_running_loop()

        self._log(logging.INFO, "Starting nao connection")
        if not await self._start_bridge():
            return False

        self.ip_self = self._get_local_ip_address()
        self._log(logging.INFO, "Local websocket server IP = " + self.ip_self)
        await self._start_websocket_communication()
        return True

    async def _start_bridge(self) -> bool:
        """Start the bridge and wire its touch events; False if Nao is unreachable."""
        try:
            await self.nao_bridge.start()
        except RobotConnectionError as e:
            self._log(logging.ERROR, f"Could not connect to Nao: {e}")
            return False
        self.nao_connected = True
        if self.config.bridge.streams.touch.enabled:
            self.nao_bridge.on_touch.subscribe(self._on_touch)
        return True

    async def stop_connection(self):
        self._log(logging.INFO, "Stopping nao connection")

        await self._stop_websocket_communication()
        if self.nao_connected:
            if self.config.bridge.streams.touch.enabled:
                self.nao_bridge.on_touch.unsubscribe(self._on_touch)
            await self.nao_bridge.stop()
            self.nao_connected = False

    # endregion

    # region Log management
    def _log(self, log_level, log):
        logger.log(log_level, log)
        if self.async_loop is None:
            return
        log_level_string = logging.getLevelName(log_level)
        message_data = {"log": log, "logLevel": log_level_string}
        asyncio.run_coroutine_threadsafe(
            self._send_to_websocket_client("Log", message_data), self.async_loop
        )

    # endregion

    # region Nao connection management
    async def _init_nao_for_interaction(self):
        self._log(logging.INFO, "Init Nao state after connection")
        await self.nao_bridge.change_eyes_color("cyan")
        await self.nao_bridge.wake_up()
        await self.nao_bridge.set_breathing_enabled(True, "Body")

    async def _reset_nao_after_interaction(self):
        self._log(logging.INFO, "Reset Nao state after disconnection")
        await self.nao_bridge.change_eyes_color("white")
        await self.nao_bridge.set_breathing_enabled(False, "Body")
        await self.nao_bridge.rest()

    # region Streams
    def _spawn(
        self, coro: Coroutine[Any, Any, None], tasks: set[asyncio.Task[None]]
    ) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def _on_touch(self, event: TouchEvent) -> None:
        """``bridge.on_touch`` handler, on the event loop: forward as a Touch message."""
        self._log(
            logging.INFO,
            f"Touch detected with key = {event.part}, touched = {event.touched}",
        )
        message_data = {"part": event.part, "touched": event.touched}
        self._spawn(
            self._send_to_websocket_client("Touch", message_data), self._send_tasks
        )

    async def _stream_joints(self) -> None:
        async for state in self.nao_bridge.joints.changes():
            if state is None:
                continue
            message_data = {
                "jointsNames": list(state.names),
                "jointsAngles": list(state.angles),
            }
            await self._send_to_websocket_client("Joints", message_data)

    async def _stream_audio(self) -> None:
        mic = self.nao_bridge.mic
        async for chunk in self.nao_bridge.audio_input():
            message_data = {
                "rate": mic.sample_rate,
                "channels": mic.channels,
                "nbSamplesPerChannel": len(chunk) // (2 * mic.channels),
                "data": base64.b64encode(chunk).decode("ascii"),
            }
            await self._send_to_websocket_client("Audio", message_data)

    def _start_streams(self) -> None:
        streams = self.config.bridge.streams
        if streams.joints.enabled:
            self._spawn(self._stream_joints(), self._stream_tasks)
        if streams.audio.enabled:
            self._spawn(self._stream_audio(), self._stream_tasks)

    async def _stop_streams(self) -> None:
        tasks = list(self._stream_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # endregion

    # region Websocket connection management
    def _get_local_ip_address(self) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]

    async def _start_websocket_communication(self):
        asyncio.create_task(self._start_server())
        await self.websocket_server_event.wait()
        self.websocket_running = True

    async def _stop_websocket_communication(self):
        if self.websocket_running:
            if self.websocket_client:
                logger.info("Closing active WebSocket client before shutdown")
                await self._websocket_disconnection(self.websocket_client)
                logger.info("Closing active WebSocket client before shutdown ==> OK")

            self.websocket_stop_event.set()
            if self.websocket_server is not None:
                await self.websocket_server.wait_closed()
            self.websocket_server = None
            self.websocket_running = False

    async def _start_server(self):
        async with websockets.serve(
            self._websocket_handler, self.ip_self, self.websocket_port
        ) as server:
            self.websocket_server = server
            logger.info("Webssocket server created")
            self.websocket_server_event.set()
            await self.websocket_stop_event.wait()
            logger.info("WebSocket server is shutting down...")

    async def _websocket_handler(self, websocket):
        await self._websocket_connection(websocket)
        try:
            async for message in websocket:
                logger.info(f"Received message: {message}")
                try:
                    data = json.loads(message)
                    message_id = data["id"]
                    if message_id == "Command":
                        task = asyncio.create_task(
                            self._command_callback(websocket, data["data"])
                        )
                        self._command_tasks.add(task)
                        task.add_done_callback(self._command_tasks.discard)
                    else:
                        self._log(logging.ERROR, "Unknown id = " + str(message_id))
                except Exception as e:  # noqa: BLE001 - reported to the client, never fatal
                    self._log(logging.ERROR, f"Bad message ignored: {e!r}")
        finally:
            if not self.websocket_closing:
                logger.info("websocket closing from the client")
                await self._websocket_disconnection(websocket)

    async def _websocket_connection(self, websocket):
        if websocket == self.websocket_client:
            return

        if self.websocket_client and websocket != self.websocket_client:
            self._log(
                logging.INFO,
                "Received connection from another client, disconnecting previous one",
            )
            await self._websocket_disconnection(self.websocket_client)

        self.websocket_client = websocket
        if self.nao_connected:
            await self._init_nao_for_interaction()

        message_data = {
            "connected": self.nao_connected,
            "fakeRobot": self.backend == "fake",
        }
        await self._send_to_websocket_client("NaoState", message_data)
        if self.nao_connected:
            self._start_streams()

    async def _websocket_disconnection(self, websocket):
        if websocket != self.websocket_client:
            # Already disconnected (e.g. replaced by a newer client): nothing to do.
            logger.debug("disconnection of a client that is no longer attached")
            return

        await self._stop_streams()
        if self.nao_connected:
            await self._reset_nao_after_interaction()

        self.websocket_closing = True
        self._log(logging.INFO, "disconnecting from client")
        await self.websocket_client.close()
        self.websocket_client = None
        self.websocket_closing = False

    async def _send_to_websocket_client(self, message_id, message_data):
        if self.websocket_client and not self.websocket_closing:
            wrapper_message_data = {"id": message_id, "data": message_data}
            message = json.dumps(wrapper_message_data)
            # logger.info("Sending message to Websocket client = " + str(message))
            try:
                await self.websocket_client.send(message)
            except websockets.ConnectionClosed:
                pass
            except Exception as e:  # noqa: BLE001 - a failed send is logged, never fatal
                logger.error(f"failed to send message with error: {e}")

    # endregion

    # region Command messages execution
    async def _command_callback(self, websocket, data):
        try:
            command_uuid = str(data["commandUuid"])
            command_id = str(data["commandId"])
            command_data = data["commandData"]
        except (KeyError, TypeError) as e:
            self._log(logging.ERROR, f"Bad command ignored: missing {e}")
            return
        logger.info("received command " + command_id)

        if not command_id in self.command_mapping:
            error = "command not found in mapping : " + command_id
            self._log(logging.ERROR, error)
            message_data = {
                "commandUuid": command_uuid,
                "resultType": "Error",
                "message": error,
                "data": None,
            }
            await self._send_to_websocket_client("CommandEnded", message_data)
            return

        try:
            (result, data) = await self.command_mapping[command_id](command_data)
        except Exception as e:  # noqa: BLE001 - reported to the client as an Error result
            self._log(
                logging.ERROR,
                "Error in command '" + command_id + "', reason = " + str(e),
            )
            (result, data) = (False, None)

        self._log(
            logging.INFO, "sending response after applying command '" + command_id + "'"
        )
        message_data = {
            "commandUuid": command_uuid,
            "resultType": "Success" if result else "Error",
            "message": "",
            "data": data,
        }
        await self._send_to_websocket_client("CommandEnded", message_data)

    async def _apply_command_generic(self, command_data) -> tuple[bool, Any]:
        text = str(command_data["text"])

        self._log(logging.INFO, "applying command 'Generic'")
        self._log(logging.INFO, "text = " + text)
        return (True, None)

    async def _apply_command_set_tts_language(self, command_data) -> tuple[bool, Any]:
        language = str(command_data["language"])

        self._log(
            logging.INFO,
            "applying command 'SetTTSLanguage' with language = " + language,
        )
        result = await self.nao_bridge.set_tts_language(language)
        return (result, None)

    async def _apply_command_say(self, command_data) -> tuple[bool, Any]:
        text = str(command_data["text"])

        self._log(logging.INFO, "applying command 'Say' with text = " + text)
        result = await self.nao_bridge.say(text)
        return (result, None)

    async def _apply_command_stop_say(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'StopSay'")
        result = await self.nao_bridge.stop_say()
        return (result, None)

    async def _apply_command_wake_up(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'WakeUp'")
        result = await self.nao_bridge.wake_up()
        return (result, None)

    async def _apply_command_rest(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'Rest'")
        result = await self.nao_bridge.rest()
        return (result, None)

    async def _apply_command_stand_up(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'StandUp'")
        result = await self.nao_bridge.stand_up()
        return (result, None)

    async def _apply_command_sit_down(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'SitDown'")
        result = await self.nao_bridge.sit_down()
        return (result, None)

    async def _apply_command_change_eyes_color(self, command_data) -> tuple[bool, Any]:
        color = str(command_data["color"])

        self._log(
            logging.INFO, "applying command 'ChangeEyesColor' with color = " + color
        )
        result = await self.nao_bridge.change_eyes_color(color)
        return (result, None)

    async def _apply_command_get_dance_behaviors(
        self, command_data
    ) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetDanceBehaviors'")
        data: list[BehaviorInfos] = self.nao_bridge.get_dance_behaviors()
        message_data = []
        for behavior in data:
            message_data.append(
                {
                    "id": behavior.id,
                    "behaviorName": behavior.behavior_name,
                    "localizedName": asdict(behavior.localized_name),
                    "description": behavior.description,
                }
            )
        return (True, message_data)

    async def _apply_command_dance(self, command_data) -> tuple[bool, Any]:
        dance_id = str(command_data["danceId"])

        self._log(logging.INFO, "applying command 'Dance' with id = " + dance_id)
        result = await self.nao_bridge.dance(dance_id)
        return (result, None)

    async def _apply_command_stop_dance(self, command_data) -> tuple[bool, Any]:
        dance_id = str(command_data["danceId"])

        self._log(logging.INFO, "applying command 'StopDance' with id = " + dance_id)
        result = await self.nao_bridge.stop_dance(dance_id)
        return (result, None)

    async def _apply_command_get_expressive_reaction_types(
        self, command_data
    ) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetExpressiveReactionTypes'")
        message_data: list[str] = self.nao_bridge.get_expressive_reaction_types()
        return (True, message_data)

    async def _apply_command_expressive_reaction(
        self, command_data
    ) -> tuple[bool, Any]:
        reaction_type = str(command_data["reactionType"])

        self._log(
            logging.INFO,
            "applying command 'ExpressiveReaction' with reactionType = "
            + reaction_type,
        )
        result = await self.nao_bridge.expressive_reaction(reaction_type)
        return (result, None)

    async def _apply_command_stop_expressive_reaction(
        self, command_data
    ) -> tuple[bool, Any]:
        reaction_type = str(command_data["reactionType"])

        self._log(
            logging.INFO,
            "applying command 'StopExpressiveReaction' with reactionType = "
            + reaction_type,
        )
        result = await self.nao_bridge.stop_expressive_reaction(reaction_type)
        return (result, None)

    async def _apply_command_get_body_action_behaviors(
        self, command_data
    ) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetBodyActionBehaviors'")
        data: list[BehaviorInfos] = self.nao_bridge.get_body_action_behaviors()
        message_data = []
        for behavior in data:
            message_data.append(
                {
                    "id": behavior.id,
                    "behaviorName": behavior.behavior_name,
                    "localizedName": asdict(behavior.localized_name),
                    "description": behavior.description,
                }
            )
        return (True, message_data)

    async def _apply_command_body_action(self, command_data) -> tuple[bool, Any]:
        body_action_id = str(command_data["bodyActionId"])

        self._log(
            logging.INFO,
            "applying command 'BodyAction' with bodyActionId = " + body_action_id,
        )
        result = await self.nao_bridge.body_action(body_action_id)
        return (result, None)

    async def _apply_command_stop_body_action(self, command_data) -> tuple[bool, Any]:
        body_action_id = str(command_data["bodyActionId"])

        self._log(
            logging.INFO,
            "applying command 'StopBodyAction' with bodyActionId = " + body_action_id,
        )
        result = await self.nao_bridge.stop_body_action(body_action_id)
        return (result, None)

    async def _apply_command_get_app_behaviors(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetAppBehaviors'")
        data: list[BehaviorInfos] = self.nao_bridge.get_app_behaviors()
        message_data = []
        for behavior in data:
            message_data.append(
                {
                    "id": behavior.id,
                    "behaviorName": behavior.behavior_name,
                    "localizedName": asdict(behavior.localized_name),
                    "description": behavior.description,
                }
            )
        return (True, message_data)

    async def _apply_command_run_app(self, command_data) -> tuple[bool, Any]:
        app_id = str(command_data["appId"])

        self._log(logging.INFO, "applying command 'RunApp' with appId = " + app_id)
        result = await self.nao_bridge.run_app(app_id)
        return (result, None)

    async def _apply_command_stop_app(self, command_data) -> tuple[bool, Any]:
        app_id = str(command_data["appId"])

        self._log(logging.INFO, "applying command 'StopApp' with appId = " + app_id)
        result = await self.nao_bridge.stop_app(app_id)
        return (result, None)

    async def _apply_command_set_basic_awareness_state(
        self, command_data
    ) -> tuple[bool, Any]:
        enabled = bool(command_data["enabled"])
        engagement_mode = str(command_data["engagementMode"])
        tracking_mode = str(command_data["trackingMode"])

        self._log(
            logging.INFO,
            "applying command 'SetBasicAwarenessState' with enabled = "
            + str(enabled)
            + ", engagementMode = "
            + engagement_mode
            + ", trackingMode = "
            + tracking_mode,
        )
        result = await self.nao_bridge.set_basic_awareness_state(
            enabled, engagement_mode, tracking_mode
        )
        return (result, None)

    async def _apply_command_set_breathing_enabled(
        self, command_data
    ) -> tuple[bool, Any]:
        enabled = bool(command_data["enabled"])
        chain_name = str(command_data["chainName"])

        self._log(
            logging.INFO,
            "applying command 'SetBreathingEnabled' with enabled = "
            + str(enabled)
            + ", chainName = "
            + chain_name,
        )
        result = await self.nao_bridge.set_breathing_enabled(enabled, chain_name)
        return (result, None)

    async def _apply_command_runbehavior(self, command_data) -> tuple[bool, Any]:
        name = str(command_data["name"])

        self._log(logging.INFO, "applying command 'RunBehavior' with name = " + name)
        result = await self.nao_bridge.run_behavior(name)
        return (result, None)

    async def _apply_command_stopbehavior(self, command_data) -> tuple[bool, Any]:
        name = str(command_data["name"])

        self._log(logging.INFO, "applying command 'StopBehavior' with name = " + name)
        result = await self.nao_bridge.stop_behavior(name)
        return (result, None)

    # endregion


async def _main(config: NaoWebsocketServerConfig) -> None:
    nao_websocket_server = NaoWebsocketServer(config)
    if await nao_websocket_server.start_connection():
        await asyncio.to_thread(input, "Press Enter to end...\n")
        logger.info("Ending received")
        await nao_websocket_server.stop_connection()
    else:
        logger.error("failed to connect to Nao, exiting")
        raise SystemExit(1)


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
