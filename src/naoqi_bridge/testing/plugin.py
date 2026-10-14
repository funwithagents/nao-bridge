"""The live-tier pytest plugin (specs/testing_support.md): the `live_target` fixture,
the `requires` marker, and the run's `live target` summary.

Opt in from your rootdir conftest — it's never registered on its own, so depending on
the bridge doesn't start a sim in an unrelated test run::

    pytest_plugins = ["naoqi_bridge.testing.plugin"]

then gate each live test on what it needs, never on which target it runs::

    @pytest.mark.requires("dances", "room_to_move")
    def test_a_dance(): ...
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .capabilities import PROFILES, check_names, missing_reason
from .target import LiveTarget, live_settings, open_target

MARKER = "requires"

# The session's target, kept for the summary after the session has released it.
_reported: LiveTarget | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker, and fail the run at once on a bad environment."""
    config.addinivalue_line(
        "markers",
        f"{MARKER}(*capabilities): run the test only where the live target has every "
        "capability; skip it elsewhere (specs/testing_support.md)",
    )
    live_settings()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A typo in a marker fails the run instead of skipping the test forever."""
    for item in items:
        for mark in item.iter_markers(MARKER):
            check_names(mark.args, f"{item.nodeid}: @pytest.mark.{MARKER}")


@pytest.fixture(scope="session", autouse=True)
def live_target() -> Iterator[LiveTarget]:
    """The session's target, up from the first test to the last: its capabilities
    probed, what the run expects of it checked. A test that drives the sim itself
    takes `live_target.sim`."""
    global _reported
    with open_target(live_settings()) as target:
        _reported = target
        yield target


@pytest.fixture(autouse=True)
def _requires_gate(request: pytest.FixtureRequest, live_target: LiveTarget) -> None:
    """Skip a test whose `requires` marks name a capability the target lacks, before
    its body runs: no bridge starts, no robot wakes."""
    needs = [name for mark in request.node.iter_markers(MARKER) for name in mark.args]
    reason = missing_reason(live_target.caps, needs)
    if reason is not None:
        pytest.skip(reason)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    target = _reported
    if target is None:
        return
    settings = live_settings().capabilities
    lines = [
        ("target", f"{target.kind}, NAOqi {target.naoqi_version or 'unknown'}"),
        ("probed", ", ".join(sorted(target.probed)) or "nothing"),
        ("declared", ", ".join(sorted(target.declared)) or "nothing"),
        (
            "expected",
            f"profile {settings.profile} "
            f"({', '.join(sorted(PROFILES[settings.profile])) or 'nothing'})"
            + (
                f" + required {', '.join(sorted(settings.required))}"
                if settings.required
                else ""
            ),
        ),
    ]
    terminalreporter.section("live target")
    for label, value in lines:
        terminalreporter.write_line(f"{label:<9} {value}")
