"""The bridge: the object a caller holds to drive Nao.

Specified by [specs/bridge.md](../../specs/bridge.md). ``NaoBridge`` owns the
``start()`` / ``stop()`` lifecycle (``async with`` over it) and exposes intent-level
async verbs returning ``bool``, the behavior catalog, and the touch / joints / audio
streams, over the robot seam in [robot.py](robot.py) — a real Nao or the fake.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Self

from .robot import AUDIO_SAMPLE_RATE, Backend, NaoRobot, build_robot

__all__ = [
    "REACTION_TYPES",
    "BehaviorCatalog",
    "BehaviorInfos",
    "BridgeError",
    "LocalizedString",
    "NaoBehavior",
    "NaoBridge",
    "build_catalog",
]

logger = logging.getLogger(__name__)

type OnTouch = Callable[[str, float], Coroutine[Any, Any, None]]
type OnJoints = Callable[[list[str], list[float]], Coroutine[Any, Any, None]]
type OnAudio = Callable[[int, int, int, str], Coroutine[Any, Any, None]]

POSTURE_SPEED = 0.8
POSTURE_MAX_TRIES = 3
JOINTS_PERIOD_S = 0.2

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


class BridgeError(RuntimeError):
    """Lifecycle misuse: starting a running bridge, reaching the robot while stopped."""


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
                name_en = entry["langToName"].get("en_US", "")
                name_fr = entry["langToName"].get("fr_FR", name_en)
                description = entry["langToDesc"].get("en_US", "")
            behaviors.append(
                NaoBehavior(
                    package_uuid=package["uuid"],
                    behavior_path=entry["path"],
                    behavior_name=behavior_name,
                    localized_name=LocalizedString(en_US=name_en, fr_FR=name_fr),
                    description=description,
                    tags=entry["langToTags"].get("en_US", []),
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

    Use ``async with NaoBridge("fake") as bridge:`` or the ``start()`` / ``stop()`` pair.
    Action verbs return ``True`` on success and never raise.
    """

    def __init__(
        self,
        backend: Backend = "real",
        *,
        ip: str = "",
        port: int = 9559,
        on_touch: OnTouch | None = None,
        on_joints: OnJoints | None = None,
        on_audio: OnAudio | None = None,
    ) -> None:
        self._backend: Backend = backend
        self._ip = ip
        self._port = port
        self._on_touch = on_touch
        self._on_joints = on_joints
        self._on_audio = on_audio

        self._robot: NaoRobot | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._joints_task: asyncio.Task[None] | None = None
        self._catalog = BehaviorCatalog()

        self.current_dances: list[str] = []
        self.current_expressive_reactions: dict[str, str] = {}
        self.current_body_actions: list[str] = []
        self.current_apps: list[str] = []
        self.current_behaviors: list[str] = []

    # region Lifecycle

    @property
    def backend(self) -> Backend:
        return self._backend

    @property
    def running(self) -> bool:
        return self._robot is not None

    @property
    def robot(self) -> NaoRobot:
        """The underlying robot (``FakeNaoRobot`` on ``fake``); only while running."""
        if self._robot is None:
            raise BridgeError("the bridge is not running; call start() first")
        return self._robot

    @property
    def raw(self) -> NaoRobot:
        return self.robot

    async def start(self) -> None:
        if self._robot is not None:
            raise BridgeError("the bridge is already running")
        robot = build_robot(self._backend, ip=self._ip, port=self._port)
        await asyncio.to_thread(robot.connect)
        self._loop = asyncio.get_running_loop()
        try:
            if self._on_touch is not None:
                await asyncio.to_thread(robot.subscribe_touch, self._forward_touch)
            if self._on_audio is not None:
                await asyncio.to_thread(robot.subscribe_audio, self._forward_audio)
            self._catalog = build_catalog(await asyncio.to_thread(robot.list_packages))
        except BaseException:
            await self._teardown(robot)
            raise
        self._robot = robot
        if self._on_joints is not None:
            self._joints_task = asyncio.create_task(
                self._joints_loop(robot, self._on_joints)
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
        await self._teardown(robot)
        self.current_dances.clear()
        self.current_expressive_reactions.clear()
        self.current_body_actions.clear()
        self.current_apps.clear()
        self.current_behaviors.clear()

    async def _teardown(self, robot: NaoRobot) -> None:
        steps: list[Callable[[], None]] = []
        if self._on_touch is not None:
            steps.append(robot.unsubscribe_touch)
        if self._on_audio is not None:
            steps.append(robot.unsubscribe_audio)
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

    def _forward_touch(self, key: str, value: float) -> None:
        if self._on_touch is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._on_touch(key, value), self._loop)

    def _forward_audio(
        self, channels: int, samples_per_channel: int, buffer: bytes
    ) -> None:
        if self._on_audio is not None and self._loop is not None:
            data = base64.b64encode(buffer).decode("ascii")
            asyncio.run_coroutine_threadsafe(
                self._on_audio(AUDIO_SAMPLE_RATE, channels, samples_per_channel, data),
                self._loop,
            )

    async def _joints_loop(self, robot: NaoRobot, on_joints: OnJoints) -> None:
        while True:
            try:
                names, angles = await asyncio.to_thread(robot.get_joints)
                await on_joints(names, angles)
            except Exception:
                logger.exception("Joints read failed")
            await asyncio.sleep(JOINTS_PERIOD_S)

    # endregion

    # region Verbs

    async def _act(self, verb: str, call: Callable[[NaoRobot], object]) -> bool:
        """Run ``call`` on the robot off the loop; ``False`` if not running, on error,
        or when the call itself reports failure by returning ``False``."""
        robot = self._robot
        if robot is None:
            logger.error("%s failed: the bridge is not running", verb)
            return False
        try:
            result = await asyncio.to_thread(call, robot)
        except Exception:
            logger.exception("%s failed", verb)
            return False
        return result is not False

    async def set_tts_language(self, language: str) -> bool:
        """Set the text-to-speech language (e.g. 'English', 'French')."""
        return await self._act("set_tts_language", lambda r: r.set_language(language))

    async def say(self, text: str) -> bool:
        """Make the robot say ``text`` (animated speech); returns once spoken."""
        return await self._act("say", lambda r: r.say(text))

    async def stop_say(self) -> bool:
        """Stop the robot talking."""
        return await self._act("stop_say", lambda r: r.stop_speech())

    async def wake_up(self) -> bool:
        """Enable the robot motors."""
        return await self._act("wake_up", lambda r: r.wake_up())

    async def rest(self) -> bool:
        """Disable the robot motors."""
        return await self._act("rest", lambda r: r.rest())

    async def stand_up(self) -> bool:
        """Go to the Stand posture."""
        return await self._act(
            "stand_up",
            lambda r: r.go_to_posture("Stand", POSTURE_SPEED, POSTURE_MAX_TRIES),
        )

    async def sit_down(self) -> bool:
        """Go to the Sit posture."""
        return await self._act(
            "sit_down",
            lambda r: r.go_to_posture("Sit", POSTURE_SPEED, POSTURE_MAX_TRIES),
        )

    async def change_eyes_color(self, color: str) -> bool:
        """Change the eyes color ('white', 'red', 'green', 'blue', 'yellow', 'magenta', 'cyan')."""
        return await self._act("change_eyes_color", lambda r: r.fade_eyes(color))

    async def set_basic_awareness_state(
        self, enabled: bool, engagement_mode: str, tracking_mode: str
    ) -> bool:
        """Configure and start/stop basic awareness."""
        return await self._act(
            "set_basic_awareness_state",
            lambda r: r.set_basic_awareness(enabled, engagement_mode, tracking_mode),
        )

    async def set_breathing_enabled(self, enabled: bool, chain_name: str) -> bool:
        """Enable or disable breathing on a chain (e.g. 'Body')."""
        return await self._act(
            "set_breathing_enabled", lambda r: r.set_breathing(chain_name, enabled)
        )

    async def run_behavior(self, behavior_name: str) -> bool:
        """Run an installed behavior; returns when it ends."""
        self.current_behaviors.append(behavior_name)
        try:
            return await self._act(
                "run_behavior", lambda r: r.run_behavior(behavior_name)
            )
        finally:
            if behavior_name in self.current_behaviors:
                self.current_behaviors.remove(behavior_name)

    async def stop_behavior(self, behavior_name: str) -> bool:
        """Stop a running behavior."""
        return await self._act(
            "stop_behavior", lambda r: r.stop_behavior(behavior_name)
        )

    # endregion

    # region Catalog verbs

    async def _play(
        self,
        kind: str,
        items: dict[str, BehaviorInfos],
        current: list[str],
        item_id: str,
    ) -> bool:
        if item_id not in items:
            logger.error("%s with id '%s' not found", kind, item_id)
            return False
        if not self.running:
            logger.error("%s '%s' failed: the bridge is not running", kind, item_id)
            return False
        current.append(item_id)
        try:
            return await self.run_behavior(items[item_id].behavior_name)
        finally:
            if item_id in current:
                current.remove(item_id)

    async def _stop(
        self,
        kind: str,
        items: dict[str, BehaviorInfos],
        current: list[str],
        item_id: str,
    ) -> bool:
        if item_id not in items:
            logger.error("%s with id '%s' not found", kind, item_id)
            return False
        if item_id not in current:
            logger.error("%s with id '%s' is not running", kind, item_id)
            return False
        return await self.stop_behavior(items[item_id].behavior_name)

    def get_dance_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.dances.values())

    async def dance(self, dance_id: str) -> bool:
        """Run a dance from ``get_dance_behaviors``; returns when it ends."""
        return await self._play(
            "Dance", self._catalog.dances, self.current_dances, dance_id
        )

    async def stop_dance(self, dance_id: str) -> bool:
        return await self._stop(
            "Dance", self._catalog.dances, self.current_dances, dance_id
        )

    def get_expressive_reaction_types(self) -> list[str]:
        return list(self._catalog.reactions)

    async def expressive_reaction(self, reaction_type: str) -> bool:
        """Play a random reaction of ``reaction_type``; returns when it ends."""
        reactions = self._catalog.reactions.get(reaction_type)
        if reactions is None:
            logger.error("Reaction type '%s' not found", reaction_type)
            return False
        if not reactions:
            logger.error("No reaction behaviors for reaction type '%s'", reaction_type)
            return False
        if not self.running:
            logger.error(
                "Reaction '%s' failed: the bridge is not running", reaction_type
            )
            return False
        behavior_name = random.choice(reactions).behavior_name
        self.current_expressive_reactions[reaction_type] = behavior_name
        try:
            return await self.run_behavior(behavior_name)
        finally:
            if self.current_expressive_reactions.get(reaction_type) == behavior_name:
                del self.current_expressive_reactions[reaction_type]

    async def stop_expressive_reaction(self, reaction_type: str) -> bool:
        """Stop the reaction ``expressive_reaction`` is playing for ``reaction_type``."""
        if reaction_type not in self._catalog.reactions:
            logger.error("Reaction type '%s' not found", reaction_type)
            return False
        behavior_name = self.current_expressive_reactions.get(reaction_type)
        if behavior_name is None:
            logger.error("Reaction type '%s' is not playing", reaction_type)
            return False
        return await self.stop_behavior(behavior_name)

    def get_body_action_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.body_actions.values())

    async def body_action(self, body_action_id: str) -> bool:
        """Run a body action from ``get_body_action_behaviors``; returns when it ends."""
        return await self._play(
            "Body action",
            self._catalog.body_actions,
            self.current_body_actions,
            body_action_id,
        )

    async def stop_body_action(self, body_action_id: str) -> bool:
        return await self._stop(
            "Body action",
            self._catalog.body_actions,
            self.current_body_actions,
            body_action_id,
        )

    def get_app_behaviors(self) -> list[BehaviorInfos]:
        return list(self._catalog.apps.values())

    async def run_app(self, app_id: str) -> bool:
        """Run an installed app from ``get_app_behaviors``; returns when it ends."""
        return await self._play("App", self._catalog.apps, self.current_apps, app_id)

    async def stop_app(self, app_id: str) -> bool:
        return await self._stop("App", self._catalog.apps, self.current_apps, app_id)

    # endregion
