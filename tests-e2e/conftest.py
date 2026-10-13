# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.

import pytest
from support import MEASUREMENTS, RUN_SIM, check_target_settings


def pytest_configure(config: pytest.Config) -> None:
    """An unknown NAOQI_E2E_TARGET or NAOQI_E2E_SIM_VERSION fails the run at once."""
    check_target_settings()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Stop the run's sim, if this run started it (specs/testing.md "Live tier: the
    target")."""
    RUN_SIM.stop()


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print what the tests measured on the robot: cancel latencies, to tune the
    bridge's stop retry on real numbers, and the audio chunk size
    (specs/testing.md "Live tier: levels of risk")."""
    if not MEASUREMENTS:
        return
    terminalreporter.section("measured live")
    width = max(len(label) for label, _ in MEASUREMENTS)
    for label, value in MEASUREMENTS:
        terminalreporter.write_line(f"{label:<{width}}  {value}")
