"""The bridge's shipped live-tier harness (specs/testing_support.md).

Install `naoqi-bridge[test]` (with `[sim]` for the sim target), opt in to the plugin
from your rootdir conftest with `pytest_plugins = ["naoqi_bridge.testing.plugin"]`, and
mark each live test with what it needs: `@pytest.mark.requires("audio_in")`.
"""

from .target import (
    LiveTarget,
    live_bridge_dict,
    live_config,
    live_session,
    requires_caps,
)

__all__ = [
    "LiveTarget",
    "live_bridge_dict",
    "live_config",
    "live_session",
    "requires_caps",
]
