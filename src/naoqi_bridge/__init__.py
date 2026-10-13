"""naoqi-bridge: drive a Naoqi robot (a real one, a simulated one, or the offline fake) from Python, MCP or WebSocket."""

from .bridge import BehaviorInfos, JointsState, LocalizedString, NaoqiBridge, TouchEvent
from .config import (
    AudioStream,
    Backend,
    ConfigError,
    JointsStream,
    NaoqiBridgeConfig,
    RobotSettings,
    SimSettings,
    SimSpawn,
    StreamSettings,
    TouchStream,
)
from .errors import (
    BridgeError,
    CommandFailedError,
    MotorsOffError,
    NotPlayingError,
    NotRunningError,
)
from .events import Event
from .microphone import MicChunk
from .observable import Observable
from .robot import RobotConnectionError, TouchPart

__all__ = [
    "AudioStream",
    "Backend",
    "BehaviorInfos",
    "BridgeError",
    "CommandFailedError",
    "ConfigError",
    "Event",
    "JointsState",
    "JointsStream",
    "LocalizedString",
    "MicChunk",
    "MotorsOffError",
    "NaoqiBridge",
    "NaoqiBridgeConfig",
    "NotPlayingError",
    "NotRunningError",
    "Observable",
    "RobotConnectionError",
    "RobotSettings",
    "SimSettings",
    "SimSpawn",
    "StreamSettings",
    "TouchEvent",
    "TouchPart",
    "TouchStream",
]
