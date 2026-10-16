"""naoqi-bridge: drive a Naoqi robot (a real one, a simulated one, or the offline fake) from Python, MCP or WebSocket."""

from .bridge import BehaviorInfos, JointsState, LocalizedString, NaoqiBridge, TouchEvent
from .camera import CameraFrame
from .config import (
    AudioStream,
    Backend,
    CameraResolution,
    CameraStream,
    CameraStreams,
    ConfigError,
    JointsStream,
    NaoqiBridgeConfig,
    RobotSettings,
    SimSettings,
    SimSpawn,
    StreamSettings,
    TouchStream,
    ViewerSettings,
)
from .errors import (
    BridgeError,
    CommandFailedError,
    MotorsOffError,
    NotPlayingError,
    NotRunningError,
    ViewerError,
)
from .events import Event
from .microphone import MicChunk
from .observable import Observable
from .robot import Camera, RobotConnectionError, TouchPart

__all__ = [
    "AudioStream",
    "Backend",
    "BehaviorInfos",
    "BridgeError",
    "Camera",
    "CameraFrame",
    "CameraResolution",
    "CameraStream",
    "CameraStreams",
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
    "ViewerError",
    "ViewerSettings",
]
