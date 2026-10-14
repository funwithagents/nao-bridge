"""The sim backend (specs/sim.md): owning or borrowing a naoqi-sim, and the bridge's
lifecycle on it. naoqi-sim's Docker side is stubbed: ``read_status`` reports a machine
the test describes, and ``NaoqiSim`` records what it is asked to do."""

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import naoqi_sim
import pytest
from naoqi_sim import NaoqiSimConfig, NaoqiSimError, StackStatus
from naoqi_sim.stack import ContainerState, NaoqiSimStatus

from naoqi_bridge import NaoqiBridge, NaoqiBridgeConfig, RobotConnectionError
from naoqi_bridge import bridge as bridge_module
from naoqi_bridge import sim as sim_module
from naoqi_bridge.config import SimSettings, SimSpawn
from naoqi_bridge.fake_robot import FakeNaoqiRobot
from naoqi_bridge.sim import SIM_URL, acquire_sim

NAOQI_VERSIONS = {"2.1": "2.1.4.13", "2.8": "2.8.7.4"}


def _status(state: str) -> StackStatus:
    """What ``read_status`` reports for a machine where naoqi-sim is ``state``:
    ``none``, ``exited`` (a dead run's leftovers), ``booting``, or ``ready-<version>``."""
    if state == "none":
        return StackStatus([], None)
    if state == "exited":
        return StackStatus(
            [ContainerState("naoqi-sim-naoqi21", "naoqi21", "exited", "")], None
        )
    if state == "booting":
        return StackStatus(
            [ContainerState("naoqi-sim-naoqi21", "naoqi21", "running", "starting")],
            None,
        )
    version = state.removeprefix("ready-")
    return StackStatus(
        [ContainerState("naoqi-sim-naoqi21", "naoqi21", "running", "healthy")],
        NaoqiSimStatus("0.1.0", NAOQI_VERSIONS[version], True, "none", "none"),
    )


@dataclass
class Machine:
    """This machine as naoqi-sim sees it: ``states`` are what successive
    ``read_status`` calls report (the last one repeats), ``events`` what happened."""

    states: list[str] = field(default_factory=lambda: ["none"])
    events: list[str] = field(default_factory=list)
    started: list[NaoqiSimConfig] = field(default_factory=list)
    start_error: NaoqiSimError | None = None
    status_error: NaoqiSimError | None = None
    # Set by a test that wants start() held until it says so.
    start_gate: asyncio.Event | None = None

    def read(self) -> StackStatus:
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return _status(state)


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Machine]:
    machine = Machine()

    async def read_status() -> StackStatus:
        if machine.status_error is not None:
            raise machine.status_error
        return machine.read()

    class StubSim:
        def __init__(self, config: NaoqiSimConfig) -> None:
            self.config = config

        @property
        def url(self) -> str:
            return SIM_URL

        async def start(self) -> None:
            if machine.start_error is not None:
                raise machine.start_error
            if machine.start_gate is not None:
                try:
                    await machine.start_gate.wait()
                except asyncio.CancelledError:
                    machine.events.append("sim aborted")  # as NaoqiSim.start() does
                    raise
            machine.started.append(self.config)
            machine.events.append("sim started")
            machine.states = [f"ready-{self.config.naoqi.version}"]

        async def status(self) -> NaoqiSimStatus:
            status = _status(f"ready-{self.config.naoqi.version}").naoqi
            assert status is not None
            return status

        async def stop(self) -> None:
            machine.events.append("sim stopped")
            machine.states = ["none"]

    monkeypatch.setattr(naoqi_sim, "read_status", read_status)
    monkeypatch.setattr(naoqi_sim, "NaoqiSim", StubSim)
    monkeypatch.setattr(sim_module, "BOOT_POLL_S", 0.01)
    yield machine


def _settings(
    spawn: SimSpawn = "auto", version: str = "2.1", **naoqi: float
) -> SimSettings:
    return SimSettings(
        spawn=spawn,
        config=NaoqiSimConfig.from_dict({"naoqi": {"version": version, **naoqi}}),
    )


# region Own it or borrow it


@pytest.mark.parametrize("spawn", ["auto", "always"])
def test_with_no_sim_running_auto_and_always_start_one_and_own_it(
    machine: Machine, spawn: SimSpawn
):
    async def scenario() -> None:
        lease = await acquire_sim(_settings(spawn, "2.8"))
        assert (lease.owned, lease.url, lease.naoqi_version) == (
            True,
            "tcp://127.0.0.1:9559",
            "2.8.7.4",
        )
        assert [c.naoqi.version for c in machine.started] == ["2.8"]
        await lease.release()
        await lease.release()  # once only

    asyncio.run(scenario())
    assert machine.events == ["sim started", "sim stopped"]


def test_leftovers_of_a_dead_run_dont_count_as_a_running_sim(machine: Machine):
    machine.states = ["exited"]
    lease = asyncio.run(acquire_sim(_settings("always")))
    assert lease.owned


@pytest.mark.parametrize("spawn", ["auto", "never"])
def test_a_ready_sim_is_borrowed_and_left_running(machine: Machine, spawn: SimSpawn):
    machine.states = ["ready-2.1"]

    async def scenario() -> None:
        lease = await acquire_sim(_settings(spawn))
        assert (lease.owned, lease.naoqi_version) == (False, "2.1.4.13")
        await lease.release()

    asyncio.run(scenario())
    assert machine.started == [] and machine.events == []


def test_never_with_no_sim_running_says_how_to_get_one(machine: Machine):
    with pytest.raises(RobotConnectionError, match="naoqi-sim run"):
        asyncio.run(acquire_sim(_settings("never")))
    assert machine.started == []


def test_always_refuses_a_sim_already_running(machine: Machine):
    machine.states = ["ready-2.1"]
    with pytest.raises(RobotConnectionError, match="already runs"):
        asyncio.run(acquire_sim(_settings("always")))
    assert machine.started == []


def test_a_borrowed_sim_of_another_version_is_refused(machine: Machine):
    machine.states = ["ready-2.8"]
    with pytest.raises(RobotConnectionError, match=r"NAOqi 2\.8\.7\.4, not 2\.1"):
        asyncio.run(acquire_sim(_settings("auto", "2.1")))


def test_a_booting_sim_is_waited_for_then_borrowed(machine: Machine):
    machine.states = ["booting", "booting", "ready-2.1"]
    lease = asyncio.run(acquire_sim(_settings("never")))
    assert not lease.owned and machine.started == []


def test_a_sim_that_never_gets_ready_fails_after_its_timeout(machine: Machine):
    machine.states = ["booting"]
    with pytest.raises(RobotConnectionError, match="not ready within 0.05 s"):
        asyncio.run(acquire_sim(_settings("auto", ready_timeout_s=0.05)))


def test_a_booting_sim_that_stops_fails_at_once(machine: Machine):
    machine.states = ["booting", "none"]
    with pytest.raises(RobotConnectionError, match="stopped"):
        asyncio.run(acquire_sim(_settings("auto")))


# endregion

# region Errors and cancellation


def test_naoqi_sims_own_errors_come_back_as_robot_connection_errors(machine: Machine):
    machine.start_error = NaoqiSimError(
        "images missing: run naoqi-sim fetch-and-build-images"
    )
    with pytest.raises(RobotConnectionError, match="fetch-and-build-images") as caught:
        asyncio.run(acquire_sim(_settings()))
    assert caught.value.__cause__ is machine.start_error

    machine.start_error = None
    machine.status_error = NaoqiSimError("Docker is not available")
    with pytest.raises(RobotConnectionError, match="Docker"):
        asyncio.run(acquire_sim(_settings()))


def test_a_cancelled_acquire_while_waiting_for_a_boot_starts_nothing(machine: Machine):
    machine.states = ["booting"]

    async def scenario() -> None:
        task = asyncio.create_task(acquire_sim(_settings()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert machine.started == []


# endregion

# region In the bridge


def _bridge(spawn: SimSpawn = "auto") -> NaoqiBridge:
    return NaoqiBridge(NaoqiBridgeConfig(backend="sim", sim=_settings(spawn)))


@pytest.fixture
def robot(monkeypatch: pytest.MonkeyPatch, machine: Machine) -> FakeNaoqiRobot:
    """The bridge's robot on sim: a fake standing in for RealNaoqiRobot at the sim's
    address (build_robot's choice is tested in test_robot.py), logging into the
    machine's events."""

    class SimRobot(FakeNaoqiRobot):
        fail_connect = False
        hold_connect = False

        def connect(self, cancel: threading.Event | None = None) -> None:
            if self.hold_connect:
                assert cancel is not None
                cancel.wait()
            if self.fail_connect or (cancel is not None and cancel.is_set()):
                raise RobotConnectionError("no answer")
            super().connect(cancel)
            machine.events.append("robot connected")

        def close(self) -> None:
            super().close()
            machine.events.append("robot closed")

    robot = SimRobot()
    monkeypatch.setattr(bridge_module, "build_robot", lambda config: robot)
    return robot


def test_a_bridge_on_sim_starts_its_sim_then_stops_it_after_the_robot(
    machine: Machine, robot: FakeNaoqiRobot
):
    async def scenario() -> None:
        async with _bridge() as bridge:
            assert bridge.backend == "sim" and bridge.running
            assert machine.events == ["sim started", "robot connected"]

    asyncio.run(scenario())
    assert machine.events[2:] == ["robot closed", "sim stopped"]


def test_a_bridge_leaves_a_borrowed_sim_running(
    machine: Machine, robot: FakeNaoqiRobot
):
    machine.states = ["ready-2.1"]

    async def scenario() -> None:
        async with _bridge("never"):
            pass

    asyncio.run(scenario())
    assert "sim stopped" not in machine.events
    assert machine.events[-1] == "robot closed"


def test_a_failed_connection_stops_the_sim_the_bridge_started(
    machine: Machine, robot: FakeNaoqiRobot
):
    robot.fail_connect = True  # pyright: ignore[reportAttributeAccessIssue]
    bridge = _bridge()
    with pytest.raises(RobotConnectionError, match="no answer"):
        asyncio.run(bridge.start())
    assert not bridge.running
    assert machine.events == ["sim started", "sim stopped"]


def test_a_start_cancelled_while_connecting_stops_the_sim(
    machine: Machine, robot: FakeNaoqiRobot
):
    robot.hold_connect = True  # pyright: ignore[reportAttributeAccessIssue]
    bridge = _bridge()

    async def scenario() -> None:
        task = asyncio.create_task(bridge.start())
        while "sim started" not in machine.events:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # the connection is in flight
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not bridge.running
    assert machine.events == ["sim started", "sim stopped"]


def test_a_start_cancelled_while_the_sim_starts_leaves_nothing_running(
    machine: Machine, robot: FakeNaoqiRobot
):
    bridge = _bridge()

    async def scenario() -> None:
        machine.start_gate = asyncio.Event()
        task = asyncio.create_task(bridge.start())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not bridge.running
    assert machine.events == ["sim aborted"]
    assert not robot.connected


# endregion
