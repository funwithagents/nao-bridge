"""The bridge's own error type (specs/bridge.md "Errors").

Its own module so the bridge's parts (``bridge.py``, ``microphone.py``) raise it
without importing each other.
"""

__all__ = ["BridgeError"]


class BridgeError(RuntimeError):
    """Lifecycle or stream misuse: starting a running bridge, reaching the robot while
    stopped, using a stream the config disabled."""
