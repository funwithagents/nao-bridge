"""The bridge: the object a caller holds to drive Nao.

Specified by [specs/bridge.md](../../specs/bridge.md). ``NaoBridge`` owns the
``start()`` / ``stop()`` lifecycle (``async with`` over it) and exposes intent-level
async verbs that raise why they failed (``errors.py``), the behavior catalog, and the robot's streams — touch
as an ``Event``, joints as an ``Observable``, the microphone as ``audio_input()``
subscribers over the mic feed — over the robot seam in [robot.py](robot.py), a real
Nao or the fake, as the ``NaoBridgeConfig`` says.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from .config import Backend, NaoBridgeConfig
from .errors import BridgeError, CommandFailedError, NotPlayingError, NotRunningError
from .events import Event
from .microphone import MicFeed
from .observable import Observable
from .robot import TOUCH_KEYS, NaoRobot, TouchPart, build_robot

__all__ = [
    "REACTION_TYPES",
    "BehaviorCatalog",
    "BehaviorInfos",
    "JointsState",
    "LocalizedString",
    "NaoBehavior",
    "NaoBridge",
    "TouchEvent",
    "TouchPart",
    "build_catalog",
]

logger = logging.getLogger(__name__)

POSTURE_SPEED = 0.8
POSTURE_MAX_TRIES = 3

REACTION_TYPES = ("Happy", "Proud", "Laugh", "Sad", "HeadTouched")
_SYSTEM_PACKAGES = frozenset(
    {"animations", "boot-config", "daps", "default_launchpad_plugins", "fall-recovery"}
)
# Applied in order to a dialog_move_arms path leaf, e.g. "UpLArm" -> "Raise left arm".
_BODY_ACTION_WORDS = {
    "LArm": "left arm",
    "RArm": "right arm",
    "BothArms": "both arms",
    "Up": "Raise ",
    "Stretch": "Stretch ",
}


@dataclass(frozen=True)
class TouchEvent:
    """A tactile head sensor changed: ``part`` is its Naoqi key."""

    part: TouchPart
    touched: bool


@dataclass(frozen=True)
class JointsState:
    """One joints sample: angles in radians, ``ts`` on the monotonic clock."""

    names: tuple[str, ...]
    angles: tuple[float, ...]
    ts: float


@dataclass
class LocalizedString:
    en_US: str
    fr_FR: str


@dataclass
class NaoBehavior:
    package_uuid: str
    behavior_path: str
    behavior_name: str
    localized_name: LocalizedString
    description: str
    tags: list[str]


@dataclass
class BehaviorInfos:
    id: str
    behavior_name: str
    localized_name: LocalizedString
    description: str


@dataclass
class BehaviorCatalog:
    dances: dict[str, BehaviorInfos] = field(default_factory=dict)
    reactions: dict[str, list[BehaviorInfos]] = field(default_factory=dict)
    body_actions: dict[str, BehaviorInfos] = field(default_factory=dict)
    apps: dict[str, BehaviorInfos] = field(default_factory=dict)


# region Catalog


def _parse_behaviors(packages: list[dict[str, Any]]) -> list[NaoBehavior]:
    behaviors: list[NaoBehavior] = []
    for package in packages:
        elems = package.get("elems", {})
        if not {"contents", "names", "descriptions"} <= elems.keys():
            continue
        if "behaviors" not in elems["contents"]:
            continue
        for entry in elems["contents"]["behaviors"]:
            if entry["path"] == ".":
                behavior_name = package["uuid"]
                name_en = elems["names"].get("en_US", "")
                name_fr = elems["names"].get("fr_FR", name_en)
                description = elems["descriptions"].get("en_US", "")
            else:
                behavior_name = package["uuid"] + "/" + entry["path"]
                names = entry.get("langToName", {})
                name_en = names.get("en_US", "")
                name_fr = names.get("fr_FR", name_en)
                description = entry.get("langToDesc", {}).get("en_US", "")
            behaviors.append(
                NaoBehavior(
                    package_uuid=package["uuid"],
                    behavior_path=entry["path"],
                    behavior_name=behavior_name,
                    localized_name=LocalizedString(en_US=name_en, fr_FR=name_fr),
                    description=description,
                    tags=entry.get("langToTags", {}).get("en_US", []),
                )
            )
    return behaviors


def _infos(behavior: NaoBehavior) -> BehaviorInfos:
    return BehaviorInfos(
        id=behavior.behavior_name,
        behavior_name=behavior.behavior_name,
        localized_name=behavior.localized_name,
        description=behavior.description,
    )


def _body_action(behavior: NaoBehavior) -> BehaviorInfos:
    leaf = behavior.behavior_path.split("/")[-1]
    description = leaf
    for word, replacement in _BODY_ACTION_WORDS.items():
        description = description.replace(word, replacement)
    return BehaviorInfos(
        id=leaf,
        behavior_name=behavior.behavior_name,
        localized_name=LocalizedString(en_US=description, fr_FR=""),
        description=description,
    )


def _is_app(behavior: NaoBehavior) -> bool:
    return (
        behavior.package_uuid not in _SYSTEM_PACKAGES
        and "dialog" not in behavior.package_uuid
        and "dance" not in behavior.description
        and behavior.behavior_path == "."
    )


def build_catalog(packages: list[dict[str, Any]]) -> BehaviorCatalog:
    """Classify a ``packages2``-shaped package list into the bridge's catalogs."""
    behaviors = _parse_behaviors(packages)
    catalog = BehaviorCatalog()
    catalog.reactions = {reaction_type: [] for reaction_type in REACTION_TYPES}
    for behavior in behaviors:
        if "dance" in behavior.description:
            catalog.dances[behavior.behavior_name] = _infos(behavior)
        if behavior.package_uuid == "animations" and behavior.behavior_path.startswith(
            "Stand/Emotions"
        ):
            for reaction_type in REACTION_TYPES:
                if reaction_type.lower() in behavior.tags:
                    catalog.reactions[reaction_type].append(_infos(behavior))
        if (
            behavior.package_uuid == "dialog_touch"
            and behavior.behavior_path == "animations/head_touched"
        ):
            catalog.reactions["HeadTouched"].append(_infos(behavior))
        if behavior.package_uuid == "dialog_move_arms":
            action = _body_action(behavior)
            catalog.body_actions[action.id] = action
        if _is_app(behavior):
            catalog.apps[behavior.behavior_name] = _infos(behavior)
    return catalog


# endregion


class NaoBridge:
    """Drive a Nao robot (``real``) or its offline stand-in (``fake``).

    Built from a ``NaoBridgeConfig`` (or a bare backend string). Use
    ``async with NaoBridge("fake") as bridge:`` or the ``start()`` / ``stop()`` pair.
    Action verbs return ``None`` on success and raise why they failed: a
    ``BridgeError`` subclass, or ``ValueError`` for an id the catalog doesn't hold.
    """

    def __init__(self, config: NaoBridgeConfig | Backend | None = None) -> None:
        if config is None:
            config = NaoBridgeConfig()
        elif isinstance(config, str):
            config = NaoBridgeConfig(backend=config)
        self._config = config

        self._robot: NaoRobot | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._joints_task: asyncio.Task[None] | None = None
        self._catalog = BehaviorCatalog()

        self.on_touch: Event[TouchEvent] = Event()
        self._joints: Observable[JointsState | None] = Observable(None)
        self._mic = MicFeed()

        # What's playing: (kind, id) -> the behavior running for it.
        self._running: dict[tuple[str, str], str] = {}
        self._running_behaviors: list[str] = []

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        return cls(NaoBridgeConfig.from_dict(data))

    @classmethod
    def from_json(cls, text: str) -> Self:
        return cls(NaoBridgeConfig.from_json(text))

    @classmethod
    def from_json_file(cls, path: str | Path) -> Self:
        return cls(NaoBridgeConfig.from_json_file(path))

    # region Lifecycle

    @property
    def config(self) -> NaoBridgeConfig:
        return self._config

    @property
    def backend(self) -> Backend:
        return self._config.backend

    @property
    def running(self) -> bool:
        return self._robot is not None

    @property
    def robot(self) -> NaoRobot:
        """The underlying robot (``FakeNaoRobot`` on ``fake``); only while running."""
        if self._robot is None:
            raise NotRunningError("the bridge is not running; call start() first")
        return self._robot

    async def start(self) -> None:
        if self._robot is not None:
            raise BridgeError("the bridge is already running")
        streams = self._config.streams
        robot = build_robot(self._config)
        await asyncio.to_thread(robot.connect)
        self._loop = asyncio.get_running_loop()
        try:
            if streams.touch.enabled:
                await asyncio.to_thread(robot.subscribe_touch, self._forward_touch)
            if streams.audio.enabled:
                await self._mic.start(robot, streams.audio.channel)
            self._catalog = build_catalog(await asyncio.to_thread(robot.list_packages))
        except BaseException:
            await self._teardown(robot)
            raise
        self._robot = robot
        if streams.joints.enabled:
            self._joints_task = asyncio.create_task(
                self._joints_loop(robot, streams.joints.period_s)
            )

    async def stop(self) -> None:
        robot = self._robot
        if robot is None:
            return
        self._robot = None
        if self._joints_task is not None:
            self._joints_task.cancel()
            await asyncio.gather(self._joints_task, return_exceptions=True)
            self._joints_task = None
            self._joints.set(None)
        await self._teardown(robot)
        self._running.clear()
        self._running_behaviors.clear()

    async def _teardown(self, robot: NaoRobot) -> None:
        await self._mic.stop()
        steps: list[Callable[[], None]] = []
        if self._config.streams.touch.enabled:
            steps.append(robot.unsubscribe_touch)
        steps.append(robot.close)
        for step in steps:
            try:
                await asyncio.to_thread(step)
            except Exception:
                logger.exception("Teardown step %s failed", step.__name__)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # endregion

    # region Streams

    @property
    def joints(self) -> Observable[JointsState | None]:
        """The latest joints sample (``None`` outside a session); ``BridgeError`` when
        the joints stream is disabled."""
        if not self._config.streams.joints.enabled:
            raise BridgeError("the joints stream is disabled (streams.joints.enabled)")
        return self._joints

    @property
    def mic(self) -> MicFeed:
        """The mic feed: ``latest()`` and ``published_count`` for samplers."""
        return self._mic

    def audio_input(self, *, preroll_s: float = 0.0) -> AsyncIterator[bytes]:
        """A new subscriber to the microphone: int16 LE mono ``bytes`` per chunk at
        ``mic.sample_rate``, every chunk in order. ``BridgeError`` when the audio stream
        is disabled, ``NotRunningError`` when the bridge is not running."""
        if not self._config.streams.audio.enabled:
            raise BridgeError("the audio stream is disabled (streams.audio.enabled)")
        _ = self.robot  # NotRunningError while stopped
        return self._mic.subscribe(preroll_s=preroll_s)

    def _forward_touch(self, key: TouchPart, value: float) -> None:
        """Naoqi's touch callback, on Naoqi's thread: emit on the bridge's loop."""
        loop = self._loop
        if loop is None or key not in TOUCH_KEYS:
            return
        event = TouchEvent(part=key, touched=int(value) == 1)
        try:
            loop.call_soon_threadsafe(self.on_touch.emit, event)
        except RuntimeError:  # the loop is closed: the session is over
            pass

    async def _joints_loop(self, robot: NaoRobot, period_s: float) -> None:
        while True:
            try:
                names, angles = await asyncio.to_thread(robot.get_joints)
                self._joints.set(
                    JointsState(tuple(names), tuple(angles), time.monotonic())
                )
            except Exception:
                logger.exception("Joints read failed")
            await asyncio.sleep(period_s)

    # endregion

    # region Verbs

    async def _act[T](self, verb: str, call: Callable[[NaoRobot], T]) -> T:
        """Run ``call`` on the robot off the loop. ``NotRunningError`` while stopped; a
        robot exception becomes ``CommandFailedError``, chained to it."""
        robot = self.robot
        try:
            return await asyncio.to_thread(call, robot)
        except Exception as e:
            raise CommandFailedError(f"{verb} failed: {e or type(e).__name__}") from e

    async def set_tts_language(self, language: str) -> None:
        """Set the text-to-speech language (e.g. 'English', 'French')."""
        await self._act("set_tts_language", lambda r: r.set_language(language))

    async def say(self, text: str) -> None:
        """Make the robot say ``text`` (animated speech); returns once spoken."""
        await self._act("say", lambda r: r.say(text))

    async def stop_say(self) -> None:
        """Stop the robot talking."""
        await self._act("stop_say", lambda r: r.stop_speech())

    async def wake_up(self) -> None:
        """Enable the robot motors."""
        await self._act("wake_up", lambda r: r.wake_up())

    async def rest(self) -> None:
        """Disable the robot motors."""
        await self._act("rest", lambda r: r.rest())

    async def _go_to_posture(self, verb: str, posture: str) -> None:
        reached = await self._act(
            verb, lambda r: r.go_to_posture(posture, POSTURE_SPEED, POSTURE_MAX_TRIES)
        )
        if not reached:
            raise CommandFailedError(
                f"{verb} failed: the robot did not reach the {posture} posture"
            )

    async def stand_up(self) -> None:
        """Go to the Stand posture."""
        await self._go_to_posture("stand_up", "Stand")

    async def sit_down(self) -> None:
        """Go to the Sit posture."""
        await self._go_to_posture("sit_down", "Sit")

    async def change_eyes_color(self, color: str) -> None:
        """Change the eyes color ('white', 'red', 'green', 'blue', 'yellow', 'magenta', 'cyan')."""
        await self._act("change_eyes_color", lambda r: r.fade_eyes(color))

    async def set_basic_awareness_state(
        self, enabled: bool, engagement_mode: str, tracking_mode: str
    ) -> None:
        """Configure and start/stop basic awareness."""
        await self._act(
            "set_basic_awareness_state",
            lambda r: r.set_basic_awareness(enabled, engagement_mode, tracking_mode),
        )

    async def set_breathing_enabled(self, enabled: bool, chain_name: str) -> None:
        """Enable or disable breathing on a chain (e.g. 'Body')."""
        await self._act(
            "set_breathing_enabled", lambda r: r.set_breathing(chain_name, enabled)
        )

    async def run_behavior(self, behavior_name: str) -> None:
        """Run an installed behavior; returns when it ends."""
        self._running_behaviors.append(behavior_name)
        try:
            await self._act("run_behavior", lambda r: r.run_behavior(behavior_name))
        finally:
            if behavior_name in self._running_behaviors:
                self._running_behaviors.remove(behavior_name)

    async def stop_behavior(self, behavior_name: str) -> None:
        """Stop a running behavior."""
        await self._act("stop_behavior", lambda r: r.stop_behavior(behavior_name))

    # endregion

    # region Catalog verbs

    def _entry[T](self, kind: str, entries: Mapping[str, T], item_id: str) -> T:
        """The catalog entry ``item_id`` of ``kind``. ``NotRunningError`` while stopped;
        ``ValueError`` naming the known ids for an unknown one."""
        _ = self.robot  # NotRunningError while stopped
        entry = entries.get(item_id)
        if entry is None:
            known = ", ".join(entries) or "none"
            raise ValueError(f"unknown {kind} '{item_id}' (known: {known})")
        return entry

    async def _play(self, kind: str, item_id: str, behavior_name: str) -> None:
        """Run ``behavior_name`` for the catalog item ``(kind, item_id)``, tracked as
        playing until it ends."""
        key = (kind, item_id)
        self._running[key] = behavior_name
        try:
            await self.run_behavior(behavior_name)
        finally:
            if self._running.get(key) == behavior_name:
                del self._running[key]

    async def _stop(self, kind: str, known: Mapping[str, object], item_id: str) -> None:
        """Stop the behavior playing for ``(kind, item_id)``; ``ValueError`` for an
        unknown id, ``NotPlayingError`` for one that isn't playing."""
        self._entry(kind, known, item_id)
        behavior_name = self._running.get((kind, item_id))
        if behavior_name is None:
            raise NotPlayingError(f"{kind} '{item_id}' is not playing")
        await self.stop_behavior(behavior_name)

    def _playing(self, kind: str) -> tuple[str, ...]:
        return tuple(item_id for k, item_id in self._running if k == kind)

    @property
    def current_dances(self) -> tuple[str, ...]:
        return self._playing("dance")

    @property
    def current_body_actions(self) -> tuple[str, ...]:
        return self._playing("body action")

    @property
    def current_apps(self) -> tuple[str, ...]:
        return self._playing("app")

    @property
    def current_expressive_reactions(self) -> Mapping[str, str]:
        """Reaction type → the behavior ``expressive_reaction`` is playing for it."""
        return MappingProxyType(
            {
                item_id: behavior
                for (k, item_id), behavior in self._running.items()
                if k == "reaction type"
            }
        )

    @property
    def current_behaviors(self) -> tuple[str, ...]:
        """Every behavior ``run_behavior`` is running, catalog verbs included."""
        return tuple(self._running_behaviors)

    def get_dance_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.dances.values())

    async def dance(self, dance_id: str) -> None:
        """Run a dance from ``get_dance_behaviors``; returns when it ends."""
        dance = self._entry("dance", self._catalog.dances, dance_id)
        await self._play("dance", dance_id, dance.behavior_name)

    async def stop_dance(self, dance_id: str) -> None:
        await self._stop("dance", self._catalog.dances, dance_id)

    def get_expressive_reaction_types(self) -> list[str]:
        return list(self._catalog.reactions)

    async def expressive_reaction(self, reaction_type: str) -> None:
        """Play a random reaction of ``reaction_type``; returns when it ends."""
        reactions = self._entry("reaction type", self._catalog.reactions, reaction_type)
        if not reactions:
            raise ValueError(
                f"no behaviors installed for reaction type '{reaction_type}'"
            )
        behavior_name = random.choice(reactions).behavior_name
        await self._play("reaction type", reaction_type, behavior_name)

    async def stop_expressive_reaction(self, reaction_type: str) -> None:
        """Stop the reaction ``expressive_reaction`` is playing for ``reaction_type``."""
        await self._stop("reaction type", self._catalog.reactions, reaction_type)

    def get_body_action_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.body_actions.values())

    async def body_action(self, body_action_id: str) -> None:
        """Run a body action from ``get_body_action_behaviors``; returns when it ends."""
        action = self._entry("body action", self._catalog.body_actions, body_action_id)
        await self._play("body action", body_action_id, action.behavior_name)

    async def stop_body_action(self, body_action_id: str) -> None:
        await self._stop("body action", self._catalog.body_actions, body_action_id)

    def get_app_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.apps.values())

    async def run_app(self, app_id: str) -> None:
        """Run an installed app from ``get_app_behaviors``; returns when it ends."""
        app = self._entry("app", self._catalog.apps, app_id)
        await self._play("app", app_id, app.behavior_name)

    async def stop_app(self, app_id: str) -> None:
        await self._stop("app", self._catalog.apps, app_id)

    # endregion
