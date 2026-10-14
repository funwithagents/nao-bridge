"""The viewer (specs/viewer.md): which robot it mirrors, and its place in the bridge's
lifecycle. naoqi-viewer's window is stubbed: ``NaoqiViewer`` records the config it
launches with and what happens to it, into the same event list as the robot."""

import asyncio
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import naoqi_viewer
import pytest
from naoqi_sim import NaoqiSimConfig
from naoqi_viewer import LaunchError, NaoqiViewerConfig

from naoqi_bridge import (
    NaoqiBridge,
    NaoqiBridgeConfig,
    RobotSettings,
    SimSettings,
    ViewerError,
    ViewerSettings,
)
from naoqi_bridge import bridge as bridge_module
from naoqi_bridge.fake_robot import FakeNaoqiRobot
from naoqi_bridge.naoqi_websocket_server import (
    NaoqiWebsocketServer,
    NaoqiWebsocketServerConfig,
)
from naoqi_bridge.sim import SIM_URL, SimLease
from naoqi_bridge.viewer import viewer_target

ROBOT_URL = "tcp://192.168.1.42:9600"


@dataclass
class World:
    """What happened, in order, to the robot and the viewer windows."""

    events: list[str] = field(default_factory=list)
    launched: list[NaoqiViewerConfig] = field(default_factory=list)
    launch_error: LaunchError | None = None
    # Set by a test that wants launch() held until it says so.
    launch_gate: threading.Event | None = None


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    world = World()

    class StubViewer:
        def __init__(self, config: NaoqiViewerConfig) -> None:
            self.config = config

        def launch(self) -> None:
            if world.launch_gate is not None:
                world.launch_gate.wait()
            if world.launch_error is not None:
                raise world.launch_error
            world.launched.append(self.config)
            world.events.append("viewer launched")

        def close(self) -> None:
            world.events.append("viewer closed")

    class Robot(FakeNaoqiRobot):
        def connect(self, cancel: threading.Event | None = None) -> None:
            super().connect(cancel)
            world.events.append("robot connected")

        def close(self) -> None:
            super().close()
            world.events.append("robot closed")

    monkeypatch.setattr(naoqi_viewer, "NaoqiViewer", StubViewer)
    monkeypatch.setattr(bridge_module, "build_robot", lambda config: Robot())
    yield world


def _real(viewer: ViewerSettings) -> NaoqiBridgeConfig:
    return NaoqiBridgeConfig(
        backend="real", robot=RobotSettings(ip="192.168.1.42", port=9600), viewer=viewer
    )


ON = ViewerSettings(enabled=True)


def _sim(headless: bool | None) -> NaoqiBridgeConfig:
    """A sim config whose sim shows its window (``headless`` false), doesn't (true), or
    is left to naoqi-sim's defaults (``None``)."""
    sim_config = (
        None
        if headless is None
        else NaoqiSimConfig.from_dict({"viewer": {"headless": headless}})
    )
    return NaoqiBridgeConfig(
        backend="sim", sim=SimSettings(config=sim_config), viewer=ON
    )


def _lease(owned: bool) -> SimLease:
    return SimLease(SIM_URL, owned=owned, naoqi_version="2.1.4.13")


# region Which robot it mirrors


@pytest.mark.parametrize(
    ("config", "lease", "url"),
    [
        (_real(ON), None, ROBOT_URL),
        (_sim(headless=False), _lease(owned=False), SIM_URL),
        (_sim(headless=None), _lease(owned=False), SIM_URL),
        (_sim(headless=True), _lease(owned=True), SIM_URL),
    ],
    ids=["real", "borrowed sim", "borrowed sim, defaults", "owned headless sim"],
)
def test_the_viewer_mirrors_the_robot_the_bridge_connects_to(
    config: NaoqiBridgeConfig,
    lease: SimLease | None,
    url: str,
    caplog: pytest.LogCaptureFixture,
):
    assert viewer_target(config, lease) == url
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize(
    ("config", "lease", "why"),
    [
        (NaoqiBridgeConfig(viewer=ON), None, "ignored on the fake backend"),
        (_sim(headless=False), _lease(owned=True), "shows its own window"),
        (_sim(headless=None), _lease(owned=True), "shows its own window"),
    ],
    ids=["fake", "owned sim with its window", "owned sim, defaults"],
)
def test_a_viewer_that_wont_open_is_skipped_with_a_warning_saying_why(
    config: NaoqiBridgeConfig,
    lease: SimLease | None,
    why: str,
    caplog: pytest.LogCaptureFixture,
):
    assert viewer_target(config, lease) is None
    [warning] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning.levelno == logging.WARNING and why in warning.getMessage()


def test_a_disabled_viewer_opens_nowhere_and_says_nothing(
    caplog: pytest.LogCaptureFixture,
):
    assert viewer_target(NaoqiBridgeConfig(), None) is None
    assert viewer_target(_real(ViewerSettings()), None) is None
    assert not caplog.records


# endregion

# region In the bridge


def test_the_viewer_opens_last_on_the_robot_and_closes_first(world: World):
    settings = ViewerSettings(
        enabled=True,
        config=NaoqiViewerConfig.from_dict({"ghost": True, "naoqi": {"rate_hz": 25}}),
    )

    async def scenario() -> None:
        async with NaoqiBridge(_real(settings)):
            assert world.events == ["robot connected", "viewer launched"]

    asyncio.run(scenario())
    assert world.events[2:] == ["viewer closed", "robot closed"]
    [launched] = world.launched
    assert (launched.mode, launched.headless) == ("mirror", False)
    assert (launched.naoqi.url, launched.naoqi.rate_hz) == (ROBOT_URL, 25)
    assert launched.ghost


def test_a_bridge_on_the_fake_runs_without_its_viewer(world: World):
    async def scenario() -> None:
        async with NaoqiBridge(NaoqiBridgeConfig(viewer=ON)) as bridge:
            assert bridge.running

    asyncio.run(scenario())
    assert world.launched == []


def test_a_viewer_that_cant_launch_fails_the_start_and_closes_the_robot(world: World):
    world.launch_error = LaunchError("no display")
    bridge = NaoqiBridge(_real(ON))
    with pytest.raises(ViewerError, match="no display") as caught:
        asyncio.run(bridge.start())
    assert caught.value.__cause__ is world.launch_error
    assert not bridge.running
    assert world.events == ["robot connected", "robot closed"]


def test_a_start_cancelled_while_the_viewer_launches_closes_it(world: World):
    world.launch_gate = threading.Event()
    bridge = NaoqiBridge(_real(ON))

    async def scenario() -> None:
        task = asyncio.create_task(bridge.start())
        while "robot connected" not in world.events:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # the launch is in flight
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()  # waiting for the launch, which can't be interrupted
        assert world.launch_gate is not None
        world.launch_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not bridge.running
    assert world.events == [
        "robot connected",
        "viewer launched",
        "viewer closed",
        "robot closed",
    ]


def test_a_server_whose_viewer_cant_launch_fails_its_start(world: World):
    world.launch_error = LaunchError("no display")
    server = NaoqiWebsocketServer(NaoqiWebsocketServerConfig(bridge=_real(ON)))

    async def scenario() -> None:
        assert not await server.start_connection()

    asyncio.run(scenario())
    assert not server.naoqi_bridge.running
    assert server.address is None  # never listened


# endregion
