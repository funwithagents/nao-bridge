"""Capabilities: what a live target offers, probed from it, or what the person running
the tests vouches for, declared (specs/testing_support.md "Capabilities").

A test names what it needs (`@pytest.mark.requires(...)`, `requires_caps`), never which
target it runs on; a profile names what a kind of target must offer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import pytest

logger = logging.getLogger(__name__)

# Read from the target at session start; nobody can declare them.
PROBED: tuple[str, ...] = (
    "sim",
    "audio_in",
    "audio_inject",
    "camera",
    "touch_sensors",
    "dances",
    "body_actions",
    "apps",
)


@dataclass(frozen=True)
class Declared:
    """A declared capability: the flag that declares it, and what it vouches for."""

    flag: str
    meaning: str


DECLARED: Mapping[str, Declared] = {
    "room_to_move": Declared(
        "NAOQI_E2E_ALLOW_MOTION",
        "the floor around the robot is clear and someone is watching",
    ),
    "person_present": Declared(
        "NAOQI_E2E_INTERACTIVE", "someone is at the robot to act on prompts"
    ),
    "display": Declared(
        "NAOQI_E2E_VIEWER", "the host has a display the run may open windows on"
    ),
}

CAPABILITIES: frozenset[str] = frozenset(PROBED) | frozenset(DECLARED)

# What a kind of target must offer: a missing one fails the run. Probed names, plus
# room_to_move on a sim, which the target itself grants; never what a person vouches for.
PROFILES: Mapping[str, frozenset[str]] = {
    "sim": frozenset({"sim", "audio_in", "audio_inject", "camera", "room_to_move"}),
    "nao": frozenset({"audio_in", "camera", "touch_sensors", "body_actions"}),
    "none": frozenset(),
}

DECLARED_VARIABLE = "NAOQI_E2E_DECLARED_CAPS"
PROFILE_VARIABLE = "NAOQI_E2E_PROFILE"
REQUIRED_VARIABLE = "NAOQI_E2E_REQUIRED_CAPS"


def flag_set(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def _names(value: str | None) -> list[str]:
    return [name.strip() for name in (value or "").split(",") if name.strip()]


def check_names(names: Iterable[str], where: str) -> None:
    """A `UsageError` naming the vocabulary when one of `names` isn't in it."""
    unknown = sorted(set(names) - CAPABILITIES)
    if unknown:
        raise pytest.UsageError(
            f"{where}: unknown capability {', '.join(unknown)}; "
            f"choose from {', '.join(sorted(CAPABILITIES))}"
        )


@dataclass(frozen=True)
class CapabilitySettings:
    """The run's capability settings: what is declared, and what is expected."""

    declared: frozenset[str]
    profile: str
    required: frozenset[str]

    @property
    def expected(self) -> frozenset[str]:
        return PROFILES[self.profile] | self.required


def read_capability_settings(env: Mapping[str, str], target: str) -> CapabilitySettings:
    """The capability settings in `env` for `target` (`sim` or `real`)."""
    listed = _names(env.get(DECLARED_VARIABLE))
    check_names(listed, DECLARED_VARIABLE)
    probed = sorted(set(listed) & set(PROBED))
    if probed:
        raise pytest.UsageError(
            f"{DECLARED_VARIABLE}: {', '.join(probed)} is probed from the target, "
            f"it can't be declared; declare one of {', '.join(sorted(DECLARED))}"
        )
    declared = set(listed)
    declared.update(name for name, d in DECLARED.items() if flag_set(env.get(d.flag)))
    if target == "sim":
        declared.add("room_to_move")  # a sim moves safely

    profile = env.get(PROFILE_VARIABLE) or ("sim" if target == "sim" else "none")
    if profile not in PROFILES:
        raise pytest.UsageError(
            f"{PROFILE_VARIABLE}={profile!r}: choose from {', '.join(PROFILES)}"
        )
    required = _names(env.get(REQUIRED_VARIABLE))
    check_names(required, REQUIRED_VARIABLE)
    return CapabilitySettings(frozenset(declared), profile, frozenset(required))


# region The probes


class Catalog(Protocol):
    """What the probe reads of a started bridge."""

    def get_dance_behaviors(self) -> list[Any]: ...
    def get_body_action_behaviors(self) -> list[Any]: ...
    def get_app_behaviors(self) -> list[Any]: ...


@dataclass(frozen=True)
class Probe:
    caps: frozenset[str]
    naoqi_version: str | None


def _service_names(session: Any) -> frozenset[str]:
    names: set[str] = set()
    for info in session.services():
        names.add(info["name"] if isinstance(info, Mapping) else info[0])
    return frozenset(names)


def _safely[T](what: str, read: Callable[[], T], absent: T) -> T:
    try:
        return read()
    except Exception as e:  # noqa: BLE001  (unreadable ⇒ capability absent)
        logger.warning("Probing %s failed, taken as absent: %s", what, e)
        return absent


def probe_capabilities(
    session: Any, catalog: Catalog, *, owns_fake_audio: bool
) -> Probe:
    """Probe the target over `session` (a connected `qi.Session`) and the catalog of a
    bridge started on it. `owns_fake_audio`: the session started the sim, with the
    `fake` audio input, so a test can play into its microphone."""
    listed: frozenset[str] | None = _safely(
        "the service list", lambda: _service_names(session), None
    )
    services = listed or frozenset()

    def memory(key: str) -> Any:
        return session.service("ALMemory").getData(key)

    on_sim = "NaoqiSim" in services
    caps: set[str] = set()
    if on_sim:
        caps.add("sim")
        if owns_fake_audio:
            caps.add("audio_inject")
    elif listed is not None:
        caps.add("touch_sensors")  # a robot's sensors are physical

    def source(device: str, service: str) -> bool:
        if on_sim:
            return memory(f"NaoqiSim/{device}/Source") != "none"
        return service in services

    probes: dict[str, Callable[[], bool]] = {
        "audio_in": lambda: source("Audio", "ALAudioDevice"),
        "camera": lambda: source("Camera", "ALVideoDevice"),
        "dances": lambda: bool(catalog.get_dance_behaviors()),
        "body_actions": lambda: bool(catalog.get_body_action_behaviors()),
        "apps": lambda: bool(catalog.get_app_behaviors()),
    }
    caps.update(name for name, probe in probes.items() if _safely(name, probe, False))

    def version() -> str:
        if on_sim:
            return str(memory("NaoqiSim/NaoqiVersion"))
        return str(session.service("ALSystem").systemVersion())

    naoqi_version = _safely("the NAOqi version", version, None)
    return Probe(frozenset(caps), naoqi_version)


# endregion


def missing_reason(caps: frozenset[str], needs: Iterable[str]) -> str | None:
    """Why a test needing `needs` can't run with `caps`, or `None` when it can."""
    missing = sorted(set(needs) - caps)
    if not missing:
        return None
    reasons: list[str] = []
    probed = [name for name in missing if name not in DECLARED]
    if probed:
        reasons.append(f"the target lacks {', '.join(probed)}")
    for name in missing:
        if name in DECLARED:
            d = DECLARED[name]
            reasons.append(
                f"needs {name}: set {d.flag}=1 (or {DECLARED_VARIABLE}={name}) "
                f"once {d.meaning}"
            )
    return "; ".join(reasons)
