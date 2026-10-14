"""The shipped live-tier harness, `naoqi_bridge.testing` (specs/testing_support.md):
the probes against a stub Naoqi, the environment rules, the expected-capabilities
check, the `requires` marker through `pytester`, and `live_session` on the fake."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any

import pytest

from naoqi_bridge import NaoqiBridgeConfig
from naoqi_bridge.fake_robot import FakeNaoqiRobot
from naoqi_bridge.testing import (
    LiveTarget,
    live_bridge_dict,
    live_config,
    live_session,
)
from naoqi_bridge.testing import target as target_module
from naoqi_bridge.testing.capabilities import (
    PROFILES,
    CapabilitySettings,
    missing_reason,
    probe_capabilities,
)
from naoqi_bridge.testing.target import check_expected, read_settings

pytest_plugins = ["pytester"]


# region Probes


class StubMemory:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def getData(self, key: str) -> Any:
        if key not in self._data:
            raise RuntimeError(f"ALMemory::getData: no key {key}")
        return self._data[key]


class StubSystem:
    def systemVersion(self) -> str:
        return "2.1.4.13"


class StubNaoqi:
    """A connected qi session's reads: its services and ALMemory's data."""

    def __init__(
        self, services: list[str] | None, memory: dict[str, Any] | None = None
    ) -> None:
        self._services = services
        self._memory = StubMemory(memory or {})

    def services(self) -> list[dict[str, Any]]:
        if self._services is None:
            raise RuntimeError("the service directory didn't answer")
        return [{"name": name, "serviceId": i} for i, name in enumerate(self._services)]

    def service(self, name: str) -> Any:
        if name == "ALMemory":
            return self._memory
        if name == "ALSystem" and self._services and "ALSystem" in self._services:
            return StubSystem()
        raise RuntimeError(f"no service {name}")


class StubCatalog:
    def __init__(self, dances: int = 0, body_actions: int = 0, apps: int = 0) -> None:
        self._counts = (dances, body_actions, apps)

    def get_dance_behaviors(self) -> list[Any]:
        return [object()] * self._counts[0]

    def get_body_action_behaviors(self) -> list[Any]:
        return [object()] * self._counts[1]

    def get_app_behaviors(self) -> list[Any]:
        return [object()] * self._counts[2]


SIM_SERVICES = ["NaoqiSim", "ALMemory", "ALAudioDevice", "ALVideoDevice", "ALMotion"]
ROBOT_SERVICES = ["ALMemory", "ALAudioDevice", "ALVideoDevice", "ALSystem", "ALMotion"]


def sim_memory(version: str, audio: str = "fake", camera: str = "render") -> dict:
    return {
        "NaoqiSim/NaoqiVersion": version,
        "NaoqiSim/Audio/Source": audio,
        "NaoqiSim/Camera/Source": camera,
    }


@pytest.mark.parametrize("version", ["2.1.4.13", "2.8.7.4"])
def test_the_sessions_sim_meets_the_sim_profile(version: str):
    probe = probe_capabilities(
        StubNaoqi(SIM_SERVICES, sim_memory(version)),
        StubCatalog(),  # the animations package only: no dance, body action or app
        owns_fake_audio=True,
    )
    assert probe.caps == {"sim", "audio_in", "audio_inject", "camera"}
    assert probe.naoqi_version == version
    target = LiveTarget("sim", version, probe.caps, frozenset({"room_to_move"}))
    assert PROFILES["sim"] <= target.caps


def test_a_borrowed_sim_without_devices_offers_neither_audio_nor_camera():
    # A sim the run didn't start: its own config attached no microphone or camera,
    # and its NaoqiSim handle (fake_audio) lives in another process.
    probe = probe_capabilities(
        StubNaoqi(SIM_SERVICES, sim_memory("2.1.4.13", audio="none", camera="none")),
        StubCatalog(),
        owns_fake_audio=False,
    )
    assert probe.caps == {"sim"}


def test_a_stock_robot_meets_the_nao_profile():
    probe = probe_capabilities(
        StubNaoqi(ROBOT_SERVICES),
        StubCatalog(body_actions=6, apps=2),
        owns_fake_audio=True,  # meaningless off a sim: there's no sim microphone
    )
    assert probe.caps == {"audio_in", "camera", "touch_sensors", "body_actions", "apps"}
    assert probe.naoqi_version == "2.1.4.13"
    assert PROFILES["nao"] <= probe.caps


def test_a_robot_without_a_video_device_has_no_camera():
    services = [s for s in ROBOT_SERVICES if s != "ALVideoDevice"]
    probe = probe_capabilities(
        StubNaoqi(services), StubCatalog(dances=1), owns_fake_audio=False
    )
    assert "camera" not in probe.caps
    assert {"dances", "audio_in", "touch_sensors"} <= probe.caps


def test_a_probe_that_raises_is_an_absent_capability(caplog: pytest.LogCaptureFixture):
    # The service list doesn't answer: nothing that needs it is claimed — touch
    # sensors included — and the catalog is still read.
    caplog.set_level(logging.WARNING)
    probe = probe_capabilities(
        StubNaoqi(None), StubCatalog(dances=2), owns_fake_audio=False
    )
    assert probe.caps == {"dances"}
    assert probe.naoqi_version is None
    assert any("the service list" in m for m in caplog.messages)


def test_an_unreadable_sim_key_drops_that_capability_only():
    memory = sim_memory("2.8.7.4")
    del memory["NaoqiSim/Camera/Source"]
    probe = probe_capabilities(
        StubNaoqi(SIM_SERVICES, memory), StubCatalog(), owns_fake_audio=True
    )
    assert probe.caps == {"sim", "audio_in", "audio_inject"}


# endregion

# region The environment


def test_by_default_a_headless_21_sim_held_to_the_sim_profile():
    settings = read_settings({})
    assert (settings.target, settings.sim_version, settings.port) == (
        "sim",
        "2.1",
        9559,
    )
    assert not settings.target_required
    assert settings.capabilities.declared == {"room_to_move"}  # a sim moves safely
    assert settings.capabilities.expected == PROFILES["sim"]


def test_a_robot_declares_nothing_and_expects_nothing_by_default():
    settings = read_settings({"NAOQI_E2E_TARGET": "real", "NAOQI_E2E_IP": "10.0.0.7"})
    assert settings.target_required
    assert (settings.ip, settings.port) == ("10.0.0.7", 9559)
    assert settings.capabilities.declared == frozenset()
    assert settings.capabilities.expected == frozenset()


def test_each_flag_declares_its_capability():
    settings = read_settings(
        {
            "NAOQI_E2E_TARGET": "real",
            "NAOQI_E2E_ALLOW_MOTION": "1",
            "NAOQI_E2E_INTERACTIVE": "yes",
            "NAOQI_E2E_VIEWER": "true",
        }
    )
    assert settings.capabilities.declared == {
        "room_to_move",
        "person_present",
        "display",
    }
    flags_off = read_settings({"NAOQI_E2E_TARGET": "real", "NAOQI_E2E_VIEWER": "0"})
    assert flags_off.capabilities.declared == frozenset()


def test_declared_caps_and_a_profile_with_required_ones():
    settings = read_settings(
        {
            "NAOQI_E2E_TARGET": "real",
            "NAOQI_E2E_DECLARED_CAPS": " person_present ,",
            "NAOQI_E2E_PROFILE": "nao",
            "NAOQI_E2E_REQUIRED_CAPS": "dances,room_to_move",
        }
    )
    assert settings.capabilities.declared == {"person_present"}
    assert settings.capabilities.expected == PROFILES["nao"] | {
        "dances",
        "room_to_move",
    }


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"NAOQI_E2E_TARGET": "pepper"}, "choose from sim, real"),
        ({"NAOQI_E2E_SIM_VERSION": "2.5"}, "choose from 2.1, 2.8"),
        ({"NAOQI_E2E_PORT": "nine"}, "not a port number"),
        ({"NAOQI_E2E_PROFILE": "pepper"}, "choose from sim, nao, none"),
        ({"NAOQI_E2E_DECLARED_CAPS": "dances"}, "dances is probed from the target"),
        ({"NAOQI_E2E_DECLARED_CAPS": "room_to_mov"}, "unknown capability room_to_mov"),
        ({"NAOQI_E2E_REQUIRED_CAPS": "camra"}, "unknown capability camra"),
    ],
)
def test_a_bad_environment_is_a_usage_error(env: dict[str, str], message: str):
    with pytest.raises(pytest.UsageError, match=message):
        read_settings(env)


# endregion

# region What the run expects


def test_a_target_missing_what_the_run_expects_fails_naming_it():
    target = LiveTarget(
        "sim", "2.1.4.13", frozenset({"sim"}), frozenset({"room_to_move"})
    )
    settings = CapabilitySettings(frozenset(), "sim", frozenset({"dances"}))
    with pytest.raises(pytest.fail.Exception) as failed:
        check_expected(target, settings)
    message = str(failed.value)
    assert "lacks audio_in, audio_inject, camera, dances" in message
    assert "profile sim; NAOQI_E2E_REQUIRED_CAPS=dances" in message


def test_a_target_meeting_its_profile_passes():
    target = LiveTarget(
        "real", None, frozenset(PROFILES["nao"] | {"dances"}), frozenset()
    )
    check_expected(target, CapabilitySettings(frozenset(), "nao", frozenset()))


def test_the_skip_reason_says_what_to_declare():
    reason = missing_reason(
        frozenset({"audio_in"}), ["audio_in", "dances", "room_to_move", "apps"]
    )
    assert reason is not None
    assert reason.startswith("the target lacks apps, dances; needs room_to_move")
    assert "set NAOQI_E2E_ALLOW_MOTION=1" in reason
    assert missing_reason(frozenset({"audio_in"}), ["audio_in"]) is None


# endregion

# region The marker, through pytester

GATED_TESTS = """
import pytest
from naoqi_bridge.testing import requires_caps

pytestmark = pytest.mark.requires("audio_in")

def test_any():
    pass

@pytest.mark.requires("dances")
def test_dance():
    pass

@pytest.mark.requires("person_present")
def test_touch():
    pass

@pytest.mark.requires("sim")
@pytest.mark.requires("room_to_move")
def test_marks_add_up():
    pass

def test_at_run_time(live_target):
    requires_caps(live_target, "apps")
"""

FIXED_TARGET = """
import pytest
from naoqi_bridge.testing import LiveTarget

@pytest.fixture(scope="session")
def live_target():
    return LiveTarget(
        "sim", "2.1.4.13", frozenset({"sim", "audio_in"}), frozenset({"room_to_move"})
    )
"""


@pytest.fixture
def harness(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.Pytester:
    """A pytester run on the plugin, its target replaced by a fixed one."""
    for name in ("TARGET", "ALLOW_MOTION", "INTERACTIVE", "VIEWER", "PROFILE"):
        monkeypatch.delenv(f"NAOQI_E2E_{name}", raising=False)
    target_module.live_settings.cache_clear()
    pytester.makeconftest(FIXED_TARGET)
    return pytester


def test_the_marker_runs_or_skips_each_test_by_the_targets_capabilities(
    harness: pytest.Pytester,
):
    harness.makepyfile(GATED_TESTS)
    result = harness.runpytest("-p", "naoqi_bridge.testing.plugin", "-rs")
    result.assert_outcomes(passed=2, skipped=3)
    result.stdout.fnmatch_lines(
        [
            "*: the target lacks dances",
            "*: needs person_present: set NAOQI_E2E_INTERACTIVE=1*",
            "*: the target lacks apps",
        ]
    )


def test_a_typo_in_a_marker_fails_the_run(harness: pytest.Pytester):
    harness.makepyfile(
        """
        import pytest

        @pytest.mark.requires("dnces")
        def test_typo():
            pass
        """
    )
    result = harness.runpytest("-p", "naoqi_bridge.testing.plugin")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*unknown capability dnces*"])


# endregion

# region Helpers


@pytest.fixture
def no_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target_module, "_current", None)


def eyes(robot: FakeNaoqiRobot) -> list[str]:
    """The eye colors the robot was asked for, in order."""
    return [args["color"] for method, args in robot.commands if method == "fade_eyes"]


def held(*caps: str) -> LiveTarget:
    return LiveTarget("sim", "2.1.4.13", frozenset(), frozenset(caps))


def test_a_session_that_moves_the_robot_needs_room_to_move(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(target_module, "_current", held("display"))

    async def run() -> None:
        async with live_session(NaoqiBridgeConfig(), motion=True):
            raise AssertionError("never reached: the robot would have moved")

    with pytest.raises(pytest.fail.Exception, match="requires\\('room_to_move'\\)"):
        asyncio.run(run())


def test_a_motion_session_wakes_the_robot_and_leaves_it_at_rest(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(target_module, "_current", held("room_to_move"))

    async def run() -> tuple[FakeNaoqiRobot, bool]:
        async with live_session(NaoqiBridgeConfig(), motion=True) as bridge:
            robot = bridge.robot
            assert isinstance(robot, FakeNaoqiRobot)
            await bridge.change_eyes_color("blue")
            return robot, robot.is_awake()

    robot, awake = asyncio.run(run())
    assert awake
    assert not robot.is_awake()
    assert eyes(robot) == ["blue", "white"]


def test_a_session_restores_the_eyes_even_when_the_test_fails(no_target: None):
    robots: list[FakeNaoqiRobot] = []

    async def run() -> None:
        async with live_session(NaoqiBridgeConfig()) as bridge:
            assert isinstance(bridge.robot, FakeNaoqiRobot)
            robots.append(bridge.robot)
            await bridge.change_eyes_color("red")
            raise ValueError("the test failed")

    with pytest.raises(ValueError, match="the test failed"):
        asyncio.run(run())
    assert eyes(robots[0])[-1] == "white"


def test_live_config_borrows_the_sessions_sim_or_targets_the_robot():
    sim = live_config(settings=read_settings({"NAOQI_E2E_SIM_VERSION": "2.8"}))
    assert sim.backend == "sim"
    assert sim.sim.spawn == "never"  # a test never starts a second sim
    robot = read_settings(
        {
            "NAOQI_E2E_TARGET": "real",
            "NAOQI_E2E_IP": "10.0.0.7",
            "NAOQI_E2E_PORT": "9560",
        }
    )
    config = live_config(settings=robot)
    assert (config.backend, config.robot.ip, config.robot.port) == (
        "real",
        "10.0.0.7",
        9560,
    )
    assert live_bridge_dict(settings=robot)["robot"] == {"ip": "10.0.0.7", "port": 9560}


def test_a_robot_without_an_address_skips_or_fails_as_asked():
    asked = read_settings({"NAOQI_E2E_TARGET": "real"})
    unasked = dataclasses.replace(asked, target_required=False)
    with pytest.raises(pytest.skip.Exception, match="set NAOQI_E2E_IP"):
        live_config(settings=unasked)
    with pytest.raises(pytest.fail.Exception, match="set NAOQI_E2E_IP"):
        live_config(settings=asked)


# endregion
