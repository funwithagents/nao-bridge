# Fast tier shared fixtures.
#
# If the package has process-global or singleton state (a module-level registry,
# a cached client, a configured logger), add an `autouse=True` fixture here that
# resets it before and after each test so state can't leak between tests. Keep
# this tier deterministic and network-free — anything that hits a real service
# belongs in tests-e2e/ instead.

import pytest

from nao_bridge.robot import FakeNaoRobot


@pytest.fixture(autouse=True)
def instant_fake_behaviors(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fake behaviors last 5 s by default (specs/robot.md); make them instant here so
    no test waits on one by accident. A test that needs a running behavior sets
    ``behavior_duration_s`` on its fake; one that checks the real default is marked
    ``fake_behavior_durations`` (specs/testing.md "Instant fake behaviors")."""
    if request.node.get_closest_marker("fake_behavior_durations") is None:
        monkeypatch.setattr(FakeNaoRobot, "DEFAULT_BEHAVIOR_DURATION_S", 0.0)
