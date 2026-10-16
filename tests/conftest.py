# Fast tier shared fixtures.
#
# If the package has process-global or singleton state (a module-level registry,
# a cached client, a configured logger), add an `autouse=True` fixture here that
# resets it before and after each test so state can't leak between tests. Keep
# this tier deterministic and network-free — anything that hits a real service
# belongs in tests-e2e/ instead.

import sys
import types

import pytest
from qi_stub import StubSession

from naoqi_bridge.fake_robot import FakeNaoqiRobot


@pytest.fixture(autouse=True)
def instant_fake_behaviors(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fake behaviors, speech and posture moves take time by default (specs/robot.md);
    make them instant here so no test waits on one by accident. A test that needs one
    in flight sets ``behavior_duration_s`` / ``speech_duration_s`` /
    ``posture_duration_s`` on its fake; one that checks the real defaults is marked
    ``fake_behavior_durations`` (specs/testing.md "Instant fake behaviors")."""
    if request.node.get_closest_marker("fake_behavior_durations") is None:
        monkeypatch.setattr(FakeNaoqiRobot, "DEFAULT_BEHAVIOR_DURATION_S", 0.0)
        monkeypatch.setattr(FakeNaoqiRobot, "DEFAULT_SPEECH_DURATION_S", 0.0)
        monkeypatch.setattr(FakeNaoqiRobot, "DEFAULT_POSTURE_DURATION_S", 0.0)


@pytest.fixture
def stub_qi(monkeypatch: pytest.MonkeyPatch) -> type[StubSession]:
    StubSession.failures = 0
    StubSession.silent = 0
    StubSession.connects = 0
    StubSession.closed = 0
    StubSession.futures = []
    StubSession.calls = []
    StubSession.returns = {}
    monkeypatch.setitem(sys.modules, "qi", types.SimpleNamespace(Session=StubSession))
    return StubSession
