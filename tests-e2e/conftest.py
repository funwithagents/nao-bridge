# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.
#
# The tier runs on the bridge's shipped harness, `naoqi_bridge.testing`
# (specs/testing_support.md): its plugin owns the session's target, probes its
# capabilities, and gates each test on its `@pytest.mark.requires(...)`. A consumer
# names the plugin in its rootdir conftest's `pytest_plugins`; this conftest isn't the
# rootdir's, so it registers the plugin itself.

from __future__ import annotations

import pytest
from support import MEASUREMENTS


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.import_plugin("naoqi_bridge.testing.plugin")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print what the tests measured on the robot: cancel latencies, to tune the
    bridge's stop retry on real numbers, and the audio chunk size
    (specs/testing.md "Live tier: capabilities")."""
    if not MEASUREMENTS:
        return
    terminalreporter.section("measured live")
    width = max(len(label) for label, _ in MEASUREMENTS)
    for label, value in MEASUREMENTS:
        terminalreporter.write_line(f"{label:<{width}}  {value}")
