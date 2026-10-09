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
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Self

from mcp.server.fastmcp import FastMCP

from .bridge import NaoBridge
from .config import ConfigError, JsonConfig, NaoBridgeConfig, as_choice, parse_block
from .errors import BridgeError
from .robot import RobotConnectionError

logger = logging.getLogger(__name__)

type Transport = Literal["stdio", "sse"]
TRANSPORTS: tuple[Transport, ...] = ("stdio", "sse")

# How often a start tool checks whether its behavior is playing yet.
_START_POLL_S = 0.01


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


async def _attempt(action: Awaitable[None], success: str, failure: str) -> str:
    """Await a bridge verb; the tool's result is the status line the model reads, with
    the reason when the verb failed (specs/nao-mcp-server.md "Failure reporting")."""
    try:
        await action
    except (BridgeError, ValueError) as e:
        return f"{failure}: {e}"
    return success


def _log_run_failure(failure: str, task: asyncio.Task[None]) -> None:
    """Log how a run that the tool already reported as started ended, if it failed."""
    if task.cancelled():
        return
    error = task.exception()
    if isinstance(error, (BridgeError, ValueError)):
        logger.error("%s: %s", failure, error)
    elif error is not None:
        logger.error("%s", failure, exc_info=error)


class NaoMcpServer:
    """``NaoBridge`` as MCP tools: one FastMCP server over one bridge session."""

    def __init__(self, config: NaoMcpServerConfig | None = None) -> None:
        """Build the server and its bridge from ``config`` (default: the fake robot)."""
        self.config = config or NaoMcpServerConfig()
        self.nao_bridge = NaoBridge(self.config.bridge)
        self.mcp = FastMCP("Nao")
        # Behaviors started by a tool, still running (strong references).
        self._runs: set[asyncio.Task[None]] = set()

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
            self.stop_dance,
            self.get_expressive_reaction_types,
            self.expressive_reaction,
            self.stop_expressive_reaction,
            self.get_body_actions_list,
            self.body_action,
            self.stop_body_action,
            self.get_app_list,
            self.run_app,
            self.stop_app,
            self.get_running,
        ):
            self.mcp.add_tool(tool)

    async def serve(self) -> None:
        """Connect to Nao, serve MCP until the client leaves, then disconnect.

        Over stdio, stdout is reserved for the protocol before the bridge starts, so
        nothing libqi logs while connecting or serving reaches the client.
        """
        if self.config.server.transport == "sse":
            await self._serve(self.mcp.run_sse_async)
            return
        with stdout_reserved_for_protocol():
            await self._serve(self.mcp.run_stdio_async)

    async def _serve(self, transport: Callable[[], Awaitable[None]]) -> None:
        async with self.nao_bridge:
            try:
                await transport()
            finally:
                await self._cancel_runs()

    async def _cancel_runs(self) -> None:
        """Cancel the behaviors still running; stopping the bridge then closes the
        robot, which ends them robot-side."""
        runs = list(self._runs)
        for run in runs:
            run.cancel()
        await asyncio.gather(*runs, return_exceptions=True)

    async def _start(
        self,
        action: Coroutine[Any, Any, None],
        playing: Callable[[], bool],
        success: str,
        failure: str,
    ) -> str:
        """Run a long bridge verb in a task of its own, as the WebSocket server does,
        and return once it is ``playing()`` or has ended (specs/nao-mcp-server.md
        "Behaviors return once started"): the model learns why it couldn't start,
        without holding the call for the length of the behavior."""
        task = asyncio.create_task(action)
        self._runs.add(task)
        task.add_done_callback(self._runs.discard)
        while not task.done() and not playing():
            await asyncio.wait({task}, timeout=_START_POLL_S)
        if task.done():
            return await _attempt(task, success, failure)
        task.add_done_callback(lambda t: _log_run_failure(failure, t))
        return success

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
        return await _attempt(
            self.nao_bridge.set_tts_language(language),
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
        return await _attempt(
            self.nao_bridge.say(text),
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
        return await _attempt(
            self.nao_bridge.wake_up(),
            "Nao motors are enabled",
            "Failed to enable Nao motors",
        )

    async def rest(self) -> str:
        """Disable Nao motors.
        - to be called at the end of an interaction

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.rest(),
            "Nao motors are disabled",
            "Failed to disable Nao motors",
        )

    async def stand_up(self) -> str:
        """Make Nao stand up.

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.stand_up(), "Nao stood up", "Nao failed to stand up"
        )

    async def sit_down(self) -> str:
        """Make Nao sit down.

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.sit_down(), "Nao sat down", "Nao failed to sit down"
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
        """Make Nao start a dance.
        - you need to have called the get_dance_list tool before, to know the list of available dances
        - returns as soon as the dance has started; it goes on while you call other tools
        - call get_running to know whether it is still playing, stop_dance to stop it

        Args:
            dance_id: The id of the dance to perform

        Returns:
            str: Status message indicating it started, or why it failed to
        """
        return await self._start(
            self.nao_bridge.dance(dance_id),
            lambda: dance_id in self.nao_bridge.current_dances,
            f"Nao started dancing the dance with id '{dance_id}'",
            f"Nao failed to dance the dance with id '{dance_id}'",
        )

    async def stop_dance(self, dance_id: str) -> str:
        """Make Nao stop a dance it is playing.

        Args:
            dance_id: The id of the dance to stop

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.stop_dance(dance_id),
            f"Nao has stopped the dance with id '{dance_id}'",
            f"Nao failed to stop the dance with id '{dance_id}'",
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
        """Make Nao start reacting to a specific emotion/situation.
        - you need to have called the get_expressive_reaction_types tool before, to know the list of available reactions
        - returns as soon as the reaction has started; it goes on while you call other tools
        - call get_running to know whether it is still playing, stop_expressive_reaction to stop it

        Args:
            reaction_type: The type of reaction to make

        Returns:
            str: Status message indicating it started, or why it failed to
        """
        return await self._start(
            self.nao_bridge.expressive_reaction(reaction_type),
            lambda: reaction_type in self.nao_bridge.current_expressive_reactions,
            f"Nao started reacting for type '{reaction_type}'",
            f"Nao failed to react for type '{reaction_type}'",
        )

    async def stop_expressive_reaction(self, reaction_type: str) -> str:
        """Make Nao stop a reaction it is playing.

        Args:
            reaction_type: The type of the reaction to stop

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.stop_expressive_reaction(reaction_type),
            f"Nao has stopped reacting for type '{reaction_type}'",
            f"Nao failed to stop reacting for type '{reaction_type}'",
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
        """Make Nao start a body action.
        - you need to have called the get_body_actions_list tool before, to know the list of available body actions
        - returns as soon as the body action has started; it goes on while you call other tools
        - call get_running to know whether it is still playing, stop_body_action to stop it

        Args:
            body_action_id: The id of the body action to perform

        Returns:
            str: Status message indicating it started, or why it failed to
        """
        return await self._start(
            self.nao_bridge.body_action(body_action_id),
            lambda: body_action_id in self.nao_bridge.current_body_actions,
            f"Nao started the body action with id '{body_action_id}'",
            f"Nao failed to perform the body action with id '{body_action_id}'",
        )

    async def stop_body_action(self, body_action_id: str) -> str:
        """Make Nao stop a body action it is playing.

        Args:
            body_action_id: The id of the body action to stop

        Returns:
            str: Status message indicating success or failure
        """
        return await _attempt(
            self.nao_bridge.stop_body_action(body_action_id),
            f"Nao has stopped the body action with id '{body_action_id}'",
            f"Nao failed to stop the body action with id '{body_action_id}'",
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
        """Make Nao start an app.
        - you need to have called the get_app_list tool before, to know the list of available apps
        - returns as soon as the app has started; it goes on while you call other tools
        - call get_running to know whether it is still running, stop_app to stop it

        Args:
            app_id: The id of the app to run

        Returns:
            str: Status message indicating it started, or why it failed to
        """
        return await self._start(
            self.nao_bridge.run_app(app_id),
            lambda: app_id in self.nao_bridge.current_apps,
            f"Nao started the app with id '{app_id}'",
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
        return await _attempt(
            self.nao_bridge.stop_app(app_id),
            f"Nao has stopped the app with id '{app_id}'",
            f"Nao failed to stop the app with id '{app_id}'",
        )

    def get_running(self) -> str:
        """Get what Nao is playing right now: the dances, expressive reactions, body
        actions and apps started with the other tools that haven't ended yet.

        Returns:
            str: JSON object with the lists "dances", "expressive_reactions",
                "body_actions" and "apps" (ids; reaction types for reactions)
        """
        bridge = self.nao_bridge
        return json.dumps(
            {
                "dances": list(bridge.current_dances),
                "expressive_reactions": list(bridge.current_expressive_reactions),
                "body_actions": list(bridge.current_body_actions),
                "apps": list(bridge.current_apps),
            }
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
