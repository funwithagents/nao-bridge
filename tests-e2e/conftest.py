# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from support import MEASUREMENTS, check_target_settings, session_sim

if TYPE_CHECKING:
    from naoqi_sim import NaoqiSim


def pytest_configure(config: pytest.Config) -> None:
    """An unknown NAOQI_E2E_TARGET or NAOQI_E2E_SIM_VERSION fails the run at once."""
    check_target_settings()


@pytest.fixture(scope="session", autouse=True)
def live_sim() -> Iterator[NaoqiSim | None]:
    """The session's naoqi-sim, started at session start and stopped at session end
    (specs/testing.md "Live tier: the target"). A test that drives the sim itself
    (plays into its microphone) takes it; `None` on the `real` target."""
    with session_sim() as sim:
        yield sim


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
