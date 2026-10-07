import argparse
from dataclasses import asdict
import logging
import json
from threading import Thread
from typing import Any, Callable
import websockets
import asyncio
from nao_api import BehaviorInfos, NaoAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NaoWebsocketServer:
    def __init__(self,
                 fake_robot: bool,
                 with_joints_data: bool, with_audio_data: bool,
                 nao_ip: str, nao_port: int, websocket_port: int):
        """Initialize the NaoWebsocketServer instance.

        Args:
            fake_robot: Whether to use fake robot mode
            with_joints_data: Whether to send joints data
            with_audio_data: Whether to send audio data
            nao_ip: Robot IP address
            nao_port: Robot port number
            websocket_port: WebSocket port number
        """
        self.fake_robot = fake_robot
        self.with_joints_data = with_joints_data
        self.with_audio_data = with_audio_data
        self.nao_ip = nao_ip
        self.nao_port = nao_port
        self.websocket_port = websocket_port

        self.ip_self = ""

        self.websocket_server = None
        self.websocket_server_event = asyncio.Event()
        self.websocket_stop_event = asyncio.Event()
        self.websocket_running = False
        self.websocket_client = None
        self.websocket_closing = False

        self.nao_api = NaoAPI(self.fake_robot,
                              self._memory_callback_touch,
                              self._joints_callback if self.with_joints_data else None,
                              self._audio_callback if self.with_audio_data else None,
                              self.nao_ip, self.nao_port)
        self.nao_connected = False

        self.command_mapping = dict[str, Callable[[Any], tuple[bool, Any]]]()
        self.command_mapping["GenericNao"] = self._apply_command_generic
        self.command_mapping["SetTTSLanguage"] = self._apply_command_set_tts_language
        self.command_mapping["Say"] = self._apply_command_say
        self.command_mapping["StopSay"] = self._apply_command_stop_say
        self.command_mapping["WakeUp"] = self._apply_command_wake_up
        self.command_mapping["Rest"] = self._apply_command_rest
        self.command_mapping["StandUp"] = self._apply_command_stand_up
        self.command_mapping["SitDown"] = self._apply_command_sit_down
        self.command_mapping["ChangeEyesColor"] = self._apply_command_change_eyes_color
        self.command_mapping["GetDanceBehaviors"] = self._apply_command_get_dance_behaviors
        self.command_mapping["Dance"] = self._apply_command_dance
        self.command_mapping["StopDance"] = self._apply_command_stop_dance
        self.command_mapping["GetExpressiveReactionTypes"] = self._apply_command_get_expressive_reaction_types
        self.command_mapping["ExpressiveReaction"] = self._apply_command_expressive_reaction
        self.command_mapping["StopExpressiveReaction"] = self._apply_command_stop_expressive_reaction
        self.command_mapping["GetBodyActionBehaviors"] = self._apply_command_get_body_action_behaviors
        self.command_mapping["BodyAction"] = self._apply_command_body_action
        self.command_mapping["StopBodyAction"] = self._apply_command_stop_body_action
        self.command_mapping["GetAppBehaviors"] = self._apply_command_get_app_behaviors
        self.command_mapping["RunApp"] = self._apply_command_run_app
        self.command_mapping["StopApp"] = self._apply_command_stop_app

        self.command_mapping["SetBasicAwarenessState"] = self._apply_command_set_basic_awareness_state
        self.command_mapping["SetBreathingEnabled"] = self._apply_command_set_breathing_enabled
        self.command_mapping["RunBehavior"] = self._apply_command_runbehavior
        self.command_mapping["StopBehavior"] = self._apply_command_stopbehavior

        self.joints_data_sync_activated = False

    #region Connection management
    async def start_connection(self) -> bool:
        self.async_loop = asyncio.get_event_loop()

        self._log(logging.INFO, "Starting nao connection")
        self.nao_connected = await self.nao_api.connect()
        if (not self.nao_connected):
            return False

        self.ip_self = self._get_local_ip_address()
        self._log(logging.INFO, "Local websocket server IP = " + self.ip_self)
        await self._start_websocket_communication()
        return True
    
    async def stop_connection(self):
        self._log(logging.INFO, "Stopping nao connection")

        if (self.nao_connected):
            await self.nao_api.disconnect()
            self.nao_connected = False
        await self._stop_websocket_communication()
    #endregion

    #region Log management
    def _log(self, log_level, log):
        logger.log(log_level, log)
        log_level_string = logging.getLevelName(log_level)
        message_data = {
            "log" : log,
            "logLevel" : log_level_string
        }
        asyncio.run_coroutine_threadsafe(self._send_to_websocket_client("Log", message_data), self.async_loop)
    #endregion

    #region Nao connection management
    async def _init_nao_for_interaction(self):
        self._log(logging.INFO, "Init Nao state after connection")
        await self.nao_api.change_eyes_color("cyan")
        await self.nao_api.wake_up()
        await self.nao_api.set_breathing_enabled(True, 'Body')

    async def _reset_nao_after_interaction(self):
        self._log(logging.INFO, "Reset Nao state after disconnection")
        await self.nao_api.change_eyes_color("white")
        await self.nao_api.set_breathing_enabled(False, 'Body')
        await self.nao_api.rest()

    #region Joints data management
    async def _joints_callback(self, joints_names, joints_angles):
        message_data = {
            "jointsNames": joints_names,
            "jointsAngles": joints_angles
        }
        await self._send_to_websocket_client("Joints", message_data)
    #endregion

    # Touch events management
    async def _memory_callback_touch(self, key, value):
        self._log(logging.INFO, "Touch detected with key = " + key + ", value = " + str(int(value)))
        message_data = {
            "part": key,
            "touched": int(value) == 1
        }
        await self._send_to_websocket_client("Touch", message_data)

    # Audio buffers management
    async def _audio_callback(self, rate, nbOfChannels, nbOfSamplesByChannel, bufferData):
        message_data = {
            "rate": rate,
            "channels": nbOfChannels,
            "nbSamplesPerChannel" : nbOfSamplesByChannel,
            "data": bufferData
        }
        await self._send_to_websocket_client("Audio", message_data)
    #endregion

    #region Websocket connection management
    def _get_local_ip_address(self) -> str:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]

    async def _start_websocket_communication(self):
        asyncio.create_task(self._start_server())
        await self.websocket_server_event.wait()
        self.websocket_running = True

    async def _stop_websocket_communication(self):
        if (self.websocket_running):
            if self.websocket_client:
                logging.info("Closing active WebSocket client before shutdown")
                await self._websocket_disconnection(self.websocket_client)
                logging.info("Closing active WebSocket client before shutdown ==> OK")

            self.websocket_stop_event.set()
            await self.websocket_server.wait_closed()
            self.websocket_server = None
            self.websocket_running = False

    async def _start_server(self):
        async with websockets.serve(self._websocket_handler, self.ip_self, self.websocket_port) as server:
            self.websocket_server = server
            logging.info("Webssocket server created")
            self.websocket_server_event.set()
            await self.websocket_stop_event.wait()
            logger.info("WebSocket server is shutting down...")

    async def _websocket_handler(self, websocket):
        await self._websocket_connection(websocket)
        try:
            async for message in websocket:
                logger.info(f"Received message: {message}")
                data = json.loads(message)
                id = data["id"]
                if (id == "Command"):
                    asyncio.create_task(self._command_callback(websocket, data["data"]))
                else:
                    self._log(logging.ERROR, "Unknown id = " + id)
        except Exception as e:
            self._log(logging.ERROR, f"Error in websocket handler: {e}")
        finally:
            if not self.websocket_closing:
                logger.info("websocket closing from the client")
                await self._websocket_disconnection(websocket)

    async def _websocket_connection(self, websocket):
        if (websocket == self.websocket_client):
            return
        
        if (self.websocket_client and websocket != self.websocket_client):
            self._log(logging.INFO, "Received connection from another client, disconnecting previous one")
            await self.websocket_client.close()
        
        self.websocket_client = websocket
        if (self.nao_connected):
            await self._init_nao_for_interaction()

        message_data = {
            "connected": self.nao_connected,
            "fakeRobot": self.fake_robot
        }
        await self._send_to_websocket_client("NaoState", message_data)

    async def _websocket_disconnection(self, websocket):
        if not self.websocket_client:
            self._log(logging.ERROR, "received disconnection message BUT was not connected, should not happen")
            return
        
        if (websocket != self.websocket_client):
            self._log(logging.ERROR, "received disconnection message from another client, should not happen")
            return
        
        if (self.nao_connected):
            await self._reset_nao_after_interaction()

        self.websocket_closing = True
        self._log(logging.INFO, "disconnecting from client")
        await self.websocket_client.close()
        self.websocket_client = None
        self.websocket_closing = False

    async def _send_to_websocket_client(self, id, message_data):
        if (self.websocket_client and not self.websocket_closing):
            wrapper_message_data = {
                "id": id,
                "data": message_data
            }
            message = json.dumps(wrapper_message_data)
            #logger.info("Sending message to Websocket client = " + str(message))
            try:
                await self.websocket_client.send(message)
            except websockets.ConnectionClosed:
                pass
            except Exception as e:
                logger.error(f"failed to send message with error: {e}")
    #endregion

    #region Command messages execution
    async def _command_callback(self, websocket, data):
        command_uuid = str(data["commandUuid"])
        command_id = str(data["commandId"])
        command_data = data["commandData"]
        logger.info("received command " + command_id)

        if (not command_id in self.command_mapping):
            error = "command not found in mapping : " + command_id
            self._log(logging.ERROR, error)
            message_data = {
                "commandUuid": command_uuid,
                "resultType": "Error",
                "message" : error
            }
            await self._send_to_websocket_client("CommandEnded", message_data)
            return

        try:
            (result, data) = await self.command_mapping[command_id](command_data)
        except Exception as e:
            self._log(logging.ERROR, "Error in command '" + command_id + "', reason = " + str(e))
            (result, data) = (False, None)

        self._log(logging.INFO, "sending response after applying command '" + command_id + "'")
        message_data = {
            "commandUuid": command_uuid,
            "resultType": "Success" if result else "Error",
            "message" : "",
            "data" : data
        }
        await self._send_to_websocket_client("CommandEnded", message_data)

    async def _apply_command_generic(self, command_data) -> tuple[bool, Any]:
        text = str(command_data["text"])
        
        self._log(logging.INFO, "applying command 'Generic'")
        self._log(logging.INFO, "text = " + text)
        return (True, None)

    async def _apply_command_set_tts_language(self, command_data) -> tuple[bool, Any]:
        language = str(command_data["language"])

        self._log(logging.INFO, "applying command 'SetTTSLanguage' with language = " + language)
        result = await self.nao_api.set_tts_language(language)
        return (result, None)

    async def _apply_command_say(self, command_data) -> tuple[bool, Any]:
        text = str(command_data["text"])
        
        self._log(logging.INFO, "applying command 'Say' with text = " + text)
        result = await self.nao_api.say(text)
        return (result, None)

    async def _apply_command_stop_say(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'StopSay'")
        result = await self.nao_api.stop_say()
        return (result, None)

    async def _apply_command_wake_up(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'WakeUp'")
        result = await self.nao_api.wake_up()
        return (result, None)

    async def _apply_command_rest(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'Rest'")
        result = await self.nao_api.rest()
        return (result, None)

    async def _apply_command_stand_up(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'StandUp'")        
        result = await self.nao_api.stand_up()
        return (result, None)

    async def _apply_command_sit_down(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'SitDown'")
        result = await self.nao_api.sit_down()
        return (result, None)

    async def _apply_command_change_eyes_color(self, command_data) -> tuple[bool, Any]:
        color = str(command_data["color"])

        self._log(logging.INFO, "applying command 'ChangeEyesColor' with color = " + color)
        result = await self.nao_api.change_eyes_color(color)
        return (result, None)
    

    async def _apply_command_get_dance_behaviors(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetDanceBehaviors'")
        data: list[BehaviorInfos] = self.nao_api.get_dance_behaviors()
        message_data = []
        for behavior in data:
            message_data.append({
                "id": behavior.id,
                "behaviorName": behavior.behavior_name,
                "localizedName": asdict(behavior.localized_name),
                "description": behavior.description
            })
        return (True, message_data)
    
    async def _apply_command_dance(self, command_data) -> tuple[bool, Any]:
        dance_id = str(command_data["danceId"])

        self._log(logging.INFO, "applying command 'Dance' with id = " + dance_id)
        result = await self.nao_api.dance(dance_id)
        return (result, None)
    
    async def _apply_command_stop_dance(self, command_data) -> tuple[bool, Any]:
        dance_id = str(command_data["danceId"])

        self._log(logging.INFO, "applying command 'StopDance' with id = " + dance_id)
        result = await self.nao_api.stop_dance(dance_id)
        return (result, None)
    
    async def _apply_command_get_expressive_reaction_types(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetExpressiveReactionTypes'")
        message_data: list[str] = self.nao_api.get_expressive_reaction_types()
        return (True, message_data)
    
    async def _apply_command_expressive_reaction(self, command_data) -> tuple[bool, Any]:
        reaction_type = str(command_data["reactionType"])

        self._log(logging.INFO, "applying command 'ExpressiveReaction' with reactionType = " + reaction_type)
        result = await self.nao_api.expressive_reaction(reaction_type)
        return (result, None)
    
    async def _apply_command_stop_expressive_reaction(self, command_data) -> tuple[bool, Any]:
        reaction_type = str(command_data["reactionType"])

        self._log(logging.INFO, "applying command 'StopExpressiveReaction' with reactionType = " + reaction_type)
        result = await self.nao_api.stop_expressive_reaction(reaction_type)
        return (result, None)
    
    async def _apply_command_get_body_action_behaviors(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetBodyActionBehaviors'")
        data: list[BehaviorInfos] = self.nao_api.get_body_action_behaviors()
        message_data = []
        for behavior in data:
            message_data.append({
                "id": behavior.id,
                "behaviorName": behavior.behavior_name,
                "localizedName": asdict(behavior.localized_name),
                "description": behavior.description
            })
        return (True, message_data)
    
    async def _apply_command_body_action(self, command_data) -> tuple[bool, Any]:
        body_action_id = str(command_data["bodyActionId"])

        self._log(logging.INFO, "applying command 'BodyAction' with bodyActionId = " + body_action_id)
        result = await self.nao_api.body_action(body_action_id)
        return (result, None)
    
    async def _apply_command_stop_body_action(self, command_data) -> tuple[bool, Any]:
        body_action_id = str(command_data["bodyActionId"])

        self._log(logging.INFO, "applying command 'StopBodyAction' with bodyActionId = " + body_action_id)
        result = await self.nao_api.stop_body_action(body_action_id)
        return (result, None)

    async def _apply_command_get_app_behaviors(self, command_data) -> tuple[bool, Any]:
        self._log(logging.INFO, "applying command 'GetAppBehaviors'")
        data: list[BehaviorInfos] = self.nao_api.get_app_behaviors()
        message_data = []
        for behavior in data:
            message_data.append({
                "id": behavior.id,
                "behaviorName": behavior.behavior_name,
                "localizedName": asdict(behavior.localized_name),
                "description": behavior.description
            })
        return (True, message_data)

    async def _apply_command_run_app(self, command_data) -> tuple[bool, Any]:
        app_id = str(command_data["appId"])

        self._log(logging.INFO, "applying command 'RunApp' with appId = " + app_id)
        result = await self.nao_api.run_app(app_id)
        return (result, None)

    async def _apply_command_stop_app(self, command_data) -> tuple[bool, Any]:
        app_id = str(command_data["appId"])

        self._log(logging.INFO, "applying command 'StopApp' with appId = " + app_id)
        result = await self.nao_api.stop_app(app_id)
        return (result, None)


    async def _apply_command_set_basic_awareness_state(self, command_data) -> tuple[bool, Any]:
        enabled = bool(command_data["enabled"])
        engagement_mode = str(command_data["engagementMode"])
        tracking_mode = str(command_data["trackingMode"])

        self._log(logging.INFO, "applying command 'SetBasicAwarenessState' with enabled = " + str(enabled) + ", engagementMode = " + engagement_mode + ", trackingMode = " + tracking_mode)
        result = await self.nao_api.set_basic_awareness_state(enabled, engagement_mode, tracking_mode)
        return (result, None)

    async def _apply_command_set_breathing_enabled(self, command_data) -> tuple[bool, Any]:
        enabled = bool(command_data["enabled"])
        chain_name = str(command_data["chainName"])

        self._log(logging.INFO, "applying command 'SetBreathingEnabled' with enabled = " + str(enabled) + ", chainName = " + chain_name)
        result = await self.nao_api.set_breathing_enabled(enabled, chain_name)
        return (result, None)

    async def _apply_command_runbehavior(self, command_data) -> tuple[bool, Any]:
        name = str(command_data["name"])

        self._log(logging.INFO, "applying command 'RunBehavior' with name = " + name)
        result = await self.nao_api.run_behavior(name)
        return (result, None)

    async def _apply_command_stopbehavior(self, command_data) -> tuple[bool, Any]:
        name = str(command_data["name"])

        self._log(logging.INFO, "applying command 'StopBehavior' with name = " + name)
        result = await self.nao_api.stop_behavior(name)
        return (result, None)
    #endregion

async def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="Nao MCP Server")
    parser.add_argument("--fake-robot", action="store_true",
                       help="To use this server without a real robot, everything will be faked")
    parser.add_argument("--ip", type=str, default="",
                       help="Robot IP address")
    parser.add_argument("--port", type=int, default=9559,
                       help="Naoqi port number, default is 9559")
    parser.add_argument("--websocket-port", type=int, default=8002,
                       help="WebSocket port number, default is 8002")
    parser.add_argument("--with-joints-data", action="store_true",
                       help="To enable the sending of Nao joints data")
    parser.add_argument("--with-audio-data", action="store_true",
                       help="To enable the sending of the audio buffers from Nao microphones")
    args = parser.parse_args()

    nao_websocket_server = NaoWebsocketServer(args.fake_robot,
                                              args.with_joints_data, args.with_audio_data,
                                              args.ip, args.port, args.websocket_port)
    if (await nao_websocket_server.start_connection()):
        await asyncio.to_thread(input, "Press Enter to end...\n")
        logger.info("Ending received")
        await nao_websocket_server.stop_connection()
    else:
        logger.error("failed to connect to Nao, exiting")

if __name__ == "__main__":
    asyncio.run(main())
