"""Nao MCP Server Module.

This module provides a server implementation for controlling a Nao robot through MCP.
It supports both real and fake robot modes, with comprehensive error handling and logging.
"""

import argparse
import asyncio
from dataclasses import asdict
import json
import logging
from typing import Any, Callable, Literal
from mcp.server.fastmcp import FastMCP
from nao_api import NaoAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NaoMcpServer:
    def __init__(self,
                 fake_robot: bool,
                 nao_ip: str, nao_port: int):
        """Initialize the NaoMcpServer instance.

        Args:
            fake_robot: Whether to use fake robot mode
            nao_ip: Robot IP address
            nao_port: Robot port number
        """
        self.nao_api = NaoAPI(fake_robot,
                              None, None, None,
                              nao_ip, nao_port)
        self.mcp = FastMCP("Nao")

        self._quick_add_tool(self.set_tts_language)
        self._quick_add_tool(self.say)
        self._quick_add_tool(self.wake_up)
        self._quick_add_tool(self.rest)
        self._quick_add_tool(self.stand_up)
        self._quick_add_tool(self.sit_down)
        self._quick_add_tool(self.get_dance_list)
        self._quick_add_tool(self.dance)
        self._quick_add_tool(self.get_expressive_reaction_types)
        self._quick_add_tool(self.expressive_reaction)
        self._quick_add_tool(self.get_body_actions_list)
        self._quick_add_tool(self.body_action)
        self._quick_add_tool(self.get_app_list)
        self._quick_add_tool(self.run_app)
        self._quick_add_tool(self.stop_app)

    def _quick_add_tool(self, fn: Callable[..., Any]) -> None:
        self.mcp.add_tool(fn, fn.__name__, fn.__doc__)

    def run(self, transport: Literal["stdio", "sse"] = "stdio") -> bool:
        """Run the NaoMcpServer.

        Args:
            transport: The transport to use (must be one of: stdio, sse)

        Returns:
            bool: True if the server is running, False otherwise
        """
        try:
            # Connect to Nao
            connected = asyncio.run(self.nao_api.connect())
        except Exception as e:
            logger.error("Application error: %s", e)
            return False

        if not connected:
            return False

        self.mcp.run(transport)
        return True

    #region Tools
    async def set_tts_language(self, language: str) -> str:
        """Change the language of Nao text to speech.
        
        Args:
            language: The language to set (must be one of: English, French)
            
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.set_tts_language(language)
        if result:
            return f"Nao switched language to {language}"
        return f"Nao failed to switch language to {language}"

    async def say(self, text: str) -> str:
        """Make Nao say something.
        
        Args:
            text: The text to say
            
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.say(text)
        if result:
            return f"Nao said {text}"
        return f"Nao failed to say {text}"

    async def wake_up(self) -> str:
        """Enable Nao motors for action.
        - to be called at the beginning of an interaction
        - needed before any call to other tools for movements
        
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.wake_up()
        if result:
            return "Nao motors are enabled"
        return "Failed to enable Nao motors"

    async def rest(self) -> str:
        """Disable Nao motors.
        - to be called at the end of an interaction
        
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.rest()
        if result:
            return "Nao motors are disabled"
        return "Failed to disable Nao motors"

    async def stand_up(self) -> str:
        """Make Nao stand up.
        
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.stand_up()
        if result:
            return "Nao stood up"
        return "Nao failed to stand up"

    async def sit_down(self) -> str:
        """Make Nao sit down.
        
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.sit_down()
        if result:
            return "Nao sat down"
        return "Nao failed to sit down"

    def get_dance_list(self) -> str:
        """Get the list of available dances.
        - to be called at the beginning of an interaction to know the list of available dances
        - needed before calling the dance tool
        
        Returns:
            str: JSON string containing dance information with
                - the id of the dance
                - the name in different languages
                - the name of the behavior to use to start the dance
                - the description of the dance    
        """
        logging.debug("Retrieving dance list")
        dance_behaviors = self.nao_api.get_dance_behaviors()
        return json.dumps([asdict(b) for b in dance_behaviors])

    async def dance(self, dance_id: str) -> str:
        """Make Nao perform a dance.
        - you need to have called the get_dance_list tool before, to know the list of available dances
        
        Args:
            dance_id: The id of the dance to perform
            
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.dance(dance_id)
        if result:
            return f"Nao has danced the dance with id '{dance_id}'"
        return f"Nao failed to dance the dance with id '{dance_id}'"

    def get_expressive_reaction_types(self) -> str:
        """Get the list of available reaction types.
        - to be called at the beginning of an interaction to know the list of available reactions
        - needed before calling the expressive_reaction tool
        
        Returns:
            str: JSON string containing the list of reaction types
        """
        return json.dumps(self.nao_api.get_expressive_reaction_types())

    async def expressive_reaction(self, reaction_type: str) -> str:
        """Make Nao react to a specific emotion/situation.
        - you need to have called the get_expressive_reaction_types tool before, to know the list of available reactions

        Args:
            reaction_type: The type of reaction to make
            
        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.expressive_reaction(reaction_type)
        if result:
            return f"Nao has reacted for type '{reaction_type}'"
        return f"Nao failed to react for type '{reaction_type}'"

    async def get_body_actions_list(self) -> str:
        """Get the list of available body actions.
        - to be called at the beginning of an interaction to know the list of available body actions
        - needed before calling the body_action tool

        Returns:
            str: JSON string containing the list of body actions
        """
        logging.debug("Retrieving body actions list")
        body_action_behaviors = self.nao_api.get_body_action_behaviors()
        return json.dumps([asdict(b) for b in body_action_behaviors])

    async def body_action(self, body_action_id: str) -> str:
        """Make Nao perform a body action.
        - you need to have called the get_body_actions_list tool before, to know the list of available body actions

        Args:
            body_action_id: The id of the body action to perform

        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.body_action(body_action_id)
        if result:
            return f"Nao has performed the body action with id '{body_action_id}'"
        return f"Nao failed to perform the body action with id '{body_action_id}'"

    def get_app_list(self) -> str:
        """Get the list of available apps.
        - to be called at the beginning of an interaction to know the list of available apps
        - needed before calling the run_app or stop_app tools

        Returns:
            str: JSON string containing app information with
                - the id of the app
                - the name in different languages
                - the name of the behavior to use to start the app
                - the description of the app
        """
        logging.debug("Retrieving app list")
        app_behaviors = self.nao_api.get_app_behaviors()
        return json.dumps([asdict(b) for b in app_behaviors])

    async def run_app(self, app_id: str) -> str:
        """Make Nao run an app.
        - you need to have called the get_app_list tool before, to know the list of available apps

        Args:
            app_id: The id of the app to run

        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.run_app(app_id)
        if result:
            return f"Nao has run the app with id '{app_id}'"
        return f"Nao failed to run the app with id '{app_id}'"

    async def stop_app(self, app_id: str) -> str:
        """Make Nao stop a running app.
        - you need to have called the get_app_list tool before, to know the list of available apps

        Args:
            app_id: The id of the app to stop

        Returns:
            str: Status message indicating success or failure
        """
        result = await self.nao_api.stop_app(app_id)
        if result:
            return f"Nao has stopped the app with id '{app_id}'"
        return f"Nao failed to stop the app with id '{app_id}'"
    #endregion

def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="Nao MCP Server")
    parser.add_argument("--fake-robot", action="store_true",
                       help="To use the mcp server without a real robot, everything will be faked")
    parser.add_argument("--ip", type=str, default="",
                       help="Robot IP address")
    parser.add_argument("--port", type=int, default=9559,
                       help="Naoqi port number")
    args = parser.parse_args()
    
    nao_mcp_server = NaoMcpServer(args.fake_robot,
                                  args.ip, args.port)
    nao_mcp_server.run()

if __name__ == "__main__":
    main()