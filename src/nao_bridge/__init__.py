"""Nao Bridge: drive a Naoqi robot (or its offline fake) from Python, MCP or WebSocket."""

from .bridge import BehaviorInfos, JointsState, LocalizedString, NaoBridge, TouchEvent
from .config import (
    AudioStream,
    Backend,
    ConfigError,
    JointsStream,
    NaoBridgeConfig,
    RobotSettings,
    StreamSettings,
    TouchStream,
)
from .errors import BridgeError
from .events import Event
from .microphone import MicChunk
from .observable import Observable
from .robot import RobotConnectionError, TouchPart

__all__ = [
    "AudioStream",
    "Backend",
    "BehaviorInfos",
    "BridgeError",
    "ConfigError",
    "Event",
    "JointsState",
    "JointsStream",
    "LocalizedString",
    "MicChunk",
    "NaoBridge",
    "NaoBridgeConfig",
    "Observable",
    "RobotConnectionError",
    "RobotSettings",
    "StreamSettings",
    "TouchEvent",
    "TouchPart",
    "TouchStream",
]
