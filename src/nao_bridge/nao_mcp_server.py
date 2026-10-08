"""Nao MCP Server Module.

Exposes NaoBridge actions as MCP tools for LLM agents (specs/nao-mcp-server.md),
built from a ``NaoMcpServerConfig``: the bridge's config plus the server's own.
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Self

from mcp.server.fastmcp import FastMCP

from .bridge import NaoBridge
from .config import ConfigError, JsonConfig, NaoBridgeConfig, as_choice, parse_block
from .robot import RobotConnectionError

logger = logging.getLogger(__name__)

type Transport = Literal["stdio", "sse"]
TRANSPORTS: tuple[Transport, ...] = ("stdio", "sse")


@dataclass(frozen=True)
class McpServerSettings(JsonConfig):
    """The MCP server's own settings: the ``server`` block."""

    transport: Transport = "stdio"

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(cls, data, path, transport=as_choice(TRANSPORTS))


@dataclass(frozen=True)
class NaoMcpServerConfig(JsonConfig):
    """``{"bridge": NaoBridgeConfig, "server": McpServerSettings}``; both optional."""

    bridge: NaoBridgeConfig = field(default_factory=NaoBridgeConfig)
    server: McpServerSettings = field(default_factory=McpServerSettings)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls,
            data,
            path,
            bridge=NaoBridgeConfig.parse,
            server=McpServerSettings.parse,
        )


@contextlib.contextmanager
def stdout_reserved_for_protocol() -> Iterator[None]:
    """Keep the real stdout for the MCP stdio transport only.

    Native code writes to file descriptor 1 directly: libqi's console log handler
    does from the first ``qi.Session()`` on, and Python's ``sys.stdout`` can't
    intercept it. Inside this block fd 1 points at stderr, so such writes land
    there, while ``sys.stdout`` (which the stdio transport wraps when it starts) is a
    private duplicate of the real stdout. Both are restored on exit.
    """
    sys.stdout.flush()
    real_stdout_fd = os.dup(1)  # kept here to restore fd 1 on exit
    os.dup2(2, 1)
    saved_stdout = sys.stdout
    # The transport gets its own duplicate: it closes its stream when it ends, which
    # must not take ``real_stdout_fd`` with it.
    protocol = open(os.dup(real_stdout_fd), "w", encoding="utf-8")  # noqa: SIM115 - closed below
    sys.stdout = protocol
    try:
        yield
    finally:
        if not protocol.closed:
            protocol.flush()
            protocol.close()
        sys.stdout = saved_stdout
        os.dup2(real_stdout_fd, 1)
        os.close(real_stdout_fd)


def _status(ok: bool, success: str, failure: str) -> str:
    """A tool's result: the status line the model reads."""
    return success if ok else failure


class NaoMcpServer:
    """``NaoBridge`` as MCP tools: one FastMCP server over one bridge session."""

    def __init__(self, config: NaoMcpServerConfig | None = None) -> None:
        """Build the server and its bridge from ``config`` (default: the fake robot)."""
        self.config = config or NaoMcpServerConfig()
        self.nao_bridge = NaoBridge(self.config.bridge)
        self.mcp = FastMCP("Nao")

        # Name and description come from each method's name and docstring.
        for tool in (
            self.set_tts_language,
            self.say,
            self.wake_up,
            self.rest,
            self.stand_up,
            self.sit_down,
            self.get_dance_list,
            self.dance,
            self.get_expressive_reaction_types,
            self.expressive_reaction,
            self.get_body_actions_list,
            self.body_action,
            self.get_app_list,
            self.run_app,
            self.stop_app,
        ):
            self.mcp.add_tool(tool)

    async def serve(self) -> None:
        """Connect to Nao, serve MCP until the client leaves, then disconnect.

        Over stdio, stdout is reserved for the protocol before the bridge starts, so
        nothing libqi logs while connecting or serving reaches the client.
        """
        if self.config.server.transport == "sse":
            async with self.nao_bridge:
                await self.mcp.run_sse_async()
            return
        with stdout_reserved_for_protocol():
            async with self.nao_bridge:
                await self.mcp.run_stdio_async()

    def run(self) -> bool:
        """Run the NaoMcpServer.

        Returns:
            bool: False if Nao could not be reached, True once the server has ended
        """
        try:
            asyncio.run(self.serve())
        except RobotConnectionError as e:
            logger.error("Could not connect to Nao: %s", e)
            return False
        return True

    # region Tools
    async def set_tts_language(self, language: str) -> str:
        """Change the language of Nao text to speech.

        Args:
            language: The language to set (must be one of: English, French)

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.set_tts_language(language),
            f"Nao switched language to {language}",
            f"Nao failed to switch language to {language}",
        )

    async def say(self, text: str) -> str:
        """Make Nao say something.

        Args:
            text: The text to say

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.say(text),
            f"Nao said {text}",
            f"Nao failed to say {text}",
        )

    async def wake_up(self) -> str:
        """Enable Nao motors for action.
        - to be called at the beginning of an interaction
        - needed before any call to other tools for movements

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.wake_up(),
            "Nao motors are enabled",
            "Failed to enable Nao motors",
        )

    async def rest(self) -> str:
        """Disable Nao motors.
        - to be called at the end of an interaction

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.rest(),
            "Nao motors are disabled",
            "Failed to disable Nao motors",
        )

    async def stand_up(self) -> str:
        """Make Nao stand up.

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.stand_up(), "Nao stood up", "Nao failed to stand up"
        )

    async def sit_down(self) -> str:
        """Make Nao sit down.

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.sit_down(), "Nao sat down", "Nao failed to sit down"
        )

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
        logger.debug("Retrieving dance list")
        dance_behaviors = self.nao_bridge.get_dance_behaviors()
        return json.dumps([asdict(b) for b in dance_behaviors])

    async def dance(self, dance_id: str) -> str:
        """Make Nao perform a dance.
        - you need to have called the get_dance_list tool before, to know the list of available dances

        Args:
            dance_id: The id of the dance to perform

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.dance(dance_id),
            f"Nao has danced the dance with id '{dance_id}'",
            f"Nao failed to dance the dance with id '{dance_id}'",
        )

    def get_expressive_reaction_types(self) -> str:
        """Get the list of available reaction types.
        - to be called at the beginning of an interaction to know the list of available reactions
        - needed before calling the expressive_reaction tool

        Returns:
            str: JSON string containing the list of reaction types
        """
        return json.dumps(self.nao_bridge.get_expressive_reaction_types())

    async def expressive_reaction(self, reaction_type: str) -> str:
        """Make Nao react to a specific emotion/situation.
        - you need to have called the get_expressive_reaction_types tool before, to know the list of available reactions

        Args:
            reaction_type: The type of reaction to make

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.expressive_reaction(reaction_type),
            f"Nao has reacted for type '{reaction_type}'",
            f"Nao failed to react for type '{reaction_type}'",
        )

    def get_body_actions_list(self) -> str:
        """Get the list of available body actions.
        - to be called at the beginning of an interaction to know the list of available body actions
        - needed before calling the body_action tool

        Returns:
            str: JSON string containing the list of body actions
        """
        logger.debug("Retrieving body actions list")
        body_action_behaviors = self.nao_bridge.get_body_action_behaviors()
        return json.dumps([asdict(b) for b in body_action_behaviors])

    async def body_action(self, body_action_id: str) -> str:
        """Make Nao perform a body action.
        - you need to have called the get_body_actions_list tool before, to know the list of available body actions

        Args:
            body_action_id: The id of the body action to perform

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.body_action(body_action_id),
            f"Nao has performed the body action with id '{body_action_id}'",
            f"Nao failed to perform the body action with id '{body_action_id}'",
        )

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
        logger.debug("Retrieving app list")
        app_behaviors = self.nao_bridge.get_app_behaviors()
        return json.dumps([asdict(b) for b in app_behaviors])

    async def run_app(self, app_id: str) -> str:
        """Make Nao run an app.
        - you need to have called the get_app_list tool before, to know the list of available apps

        Args:
            app_id: The id of the app to run

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.run_app(app_id),
            f"Nao has run the app with id '{app_id}'",
            f"Nao failed to run the app with id '{app_id}'",
        )

    async def stop_app(self, app_id: str) -> str:
        """Make Nao stop a running app.
        - you need to have called the get_app_list tool before, to know the list of available apps

        Args:
            app_id: The id of the app to stop

        Returns:
            str: Status message indicating success or failure
        """
        return _status(
            await self.nao_bridge.stop_app(app_id),
            f"Nao has stopped the app with id '{app_id}'",
            f"Nao failed to stop the app with id '{app_id}'",
        )

    # endregion


def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="Nao MCP Server")
    parser.add_argument(
        "--config",
        help="Path to a JSON server config (default: the fake robot over stdio)",
    )
    args = parser.parse_args()
    try:
        config = (
            NaoMcpServerConfig.from_json_file(args.config)
            if args.config
            else NaoMcpServerConfig()
        )
    except ConfigError as e:
        parser.error(str(e))

    # Logs go to stderr: stdout is the MCP stdio transport.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if not NaoMcpServer(config).run():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
