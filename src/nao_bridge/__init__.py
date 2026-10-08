"""Nao Bridge: drive a Naoqi robot (or its offline fake) from Python, MCP or WebSocket."""

from .bridge import BehaviorInfos, BridgeError, LocalizedString, NaoBridge
from .robot import Backend, RobotConnectionError

__all__ = [
    "Backend",
    "BehaviorInfos",
    "BridgeError",
    "LocalizedString",
    "NaoBridge",
    "RobotConnectionError",
]
