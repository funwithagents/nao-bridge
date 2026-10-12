"""The bridge's own error types (specs/bridge.md "Errors").

Their own module so the bridge's parts (``bridge.py``, ``microphone.py``) raise them
without importing each other.
"""

__all__ = [
    "BridgeError",
    "CommandFailedError",
    "MotorsOffError",
    "NotPlayingError",
    "NotRunningError",
]


class BridgeError(RuntimeError):
    """The base of the bridge's errors; raised as such for lifecycle and stream misuse:
    starting a running bridge, using a stream the config disabled."""


class NotRunningError(BridgeError):
    """A verb, ``robot`` or ``audio_input()`` on a bridge that isn't running."""


class NotPlayingError(BridgeError):
    """A catalog stop verb for an item that isn't playing."""


class MotorsOffError(BridgeError):
    """A verb that moves the body while the robot's motors are off (call ``wake_up()``)."""


class CommandFailedError(BridgeError):
    """The robot failed a verb; a Naoqi exception is chained as ``__cause__``."""
