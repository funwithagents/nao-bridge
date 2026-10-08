"""Bridge configuration: ``NaoBridgeConfig`` and its blocks (specs/config.md).

One declarative description of which robot to drive and what to stream from it, built
in code or loaded with the ``from_dict`` / ``from_json`` / ``from_json_file`` trio.
Invalid input raises ``ConfigError`` naming the offending key path. Each block checks
its own ranges on construction; the loaders also check shape, types and unknown keys.

The field readers (``read_*``) and the ``JsonConfig`` base are public so configs that
wrap a ``NaoBridgeConfig`` (the servers') validate the same way. This module imports
neither ``qi`` nor ``mcp`` nor ``websockets``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

__all__ = [
    "AUDIO_CHANNELS",
    "BACKENDS",
    "AudioChannel",
    "AudioStream",
    "Backend",
    "ConfigError",
    "JointsStream",
    "JsonConfig",
    "NaoBridgeConfig",
    "RobotSettings",
    "StreamSettings",
    "TouchStream",
    "build",
    "check_keys",
    "key_path",
    "read_bool",
    "read_choice",
    "read_int",
    "read_number",
    "read_object",
    "read_str",
]

type Backend = Literal["real", "fake"]
type AudioChannel = Literal["front", "rear", "left", "right"]
BACKENDS: tuple[Backend, ...] = ("real", "fake")
AUDIO_CHANNELS: tuple[AudioChannel, ...] = ("front", "rear", "left", "right")


class ConfigError(ValueError):
    """A malformed configuration; the message names the offending key path."""


# region Field readers


def key_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def read_object(data: Any, path: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path or 'config'} must be an object, got {type(data).__name__}"
        )
    return data  # pyright: ignore[reportUnknownVariableType]


def check_keys(data: dict[str, Any], allowed: Iterable[str], path: str) -> None:
    allowed = tuple(allowed)
    for key in data:
        if key not in allowed:
            raise ConfigError(
                f"unknown key {key_path(path, key)!r}; expected one of: {', '.join(allowed)}"
            )


def read_bool(data: dict[str, Any], key: str, default: bool, path: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key_path(path, key)} must be a boolean, got {value!r}")
    return value


def read_int(data: dict[str, Any], key: str, default: int, path: str) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key_path(path, key)} must be an integer, got {value!r}")
    return value


def read_number(data: dict[str, Any], key: str, default: float, path: str) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{key_path(path, key)} must be a number, got {value!r}")
    return float(value)


def read_str(data: dict[str, Any], key: str, default: str, path: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key_path(path, key)} must be a string, got {value!r}")
    return value


def read_choice[C: str](
    data: dict[str, Any], key: str, default: C, choices: tuple[C, ...], path: str
) -> C:
    value = data.get(key, default)
    for choice in choices:
        if value == choice:
            return choice
    expected = ", ".join(repr(c) for c in choices)
    raise ConfigError(f"{key_path(path, key)} must be one of {expected}, got {value!r}")


def build[T](factory: Callable[..., T], path: str, **kwargs: Any) -> T:
    """Construct a config block, prefixing its own validation errors with ``path``."""
    try:
        return factory(**kwargs)
    except ConfigError as e:
        raise ConfigError(key_path(path, str(e)) if path else str(e)) from None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


# endregion


class JsonConfig:
    """The loader trio, shared by every config class: ``from_json_file`` reads,
    ``from_json`` parses, ``from_dict`` validates and builds."""

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        """Validate ``data`` found at key ``path`` and build the block."""
        raise NotImplementedError

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        return cls.parse(data, "")

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigError(f"invalid JSON: {e}") from e
        return cls.from_dict(data)

    @classmethod
    def from_json_file(cls, path: str | Path) -> Self:
        file = Path(path)
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"cannot read config file {file}: {e}") from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigError(f"{file}: invalid JSON: {e}") from e
        return cls.from_dict(data)


@dataclass(frozen=True)
class RobotSettings(JsonConfig):
    """Where the real robot is; validated but not applied on ``fake``."""

    ip: str = ""
    port: int = 9559
    connect_tries: int = 10

    def __post_init__(self) -> None:
        _require(self.port > 0, f"port must be a positive integer, got {self.port}")
        _require(
            self.connect_tries > 0,
            f"connect_tries must be a positive integer, got {self.connect_tries}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("ip", "port", "connect_tries"), path)
        return build(
            cls,
            path,
            ip=read_str(obj, "ip", "", path),
            port=read_int(obj, "port", 9559, path),
            connect_tries=read_int(obj, "connect_tries", 10, path),
        )


@dataclass(frozen=True)
class TouchStream(JsonConfig):
    enabled: bool = False

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("enabled",), path)
        return build(cls, path, enabled=read_bool(obj, "enabled", False, path))


@dataclass(frozen=True)
class JointsStream(JsonConfig):
    enabled: bool = False
    period_s: float = 0.2

    def __post_init__(self) -> None:
        _require(
            math.isfinite(self.period_s) and self.period_s > 0,
            f"period_s must be a positive, finite number, got {self.period_s}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("enabled", "period_s"), path)
        return build(
            cls,
            path,
            enabled=read_bool(obj, "enabled", False, path),
            period_s=read_number(obj, "period_s", 0.2, path),
        )


@dataclass(frozen=True)
class AudioStream(JsonConfig):
    enabled: bool = False
    channel: AudioChannel = "front"

    def __post_init__(self) -> None:
        _require(
            self.channel in AUDIO_CHANNELS,
            f"channel must be one of {', '.join(map(repr, AUDIO_CHANNELS))}, "
            f"got {self.channel!r}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("enabled", "channel"), path)
        return build(
            cls,
            path,
            enabled=read_bool(obj, "enabled", False, path),
            channel=read_choice(obj, "channel", "front", AUDIO_CHANNELS, path),
        )


@dataclass(frozen=True)
class StreamSettings(JsonConfig):
    """Which robot streams the bridge subscribes to at ``start()``."""

    touch: TouchStream = field(default_factory=TouchStream)
    joints: JointsStream = field(default_factory=JointsStream)
    audio: AudioStream = field(default_factory=AudioStream)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("touch", "joints", "audio"), path)
        return build(
            cls,
            path,
            touch=TouchStream.parse(obj.get("touch", {}), key_path(path, "touch")),
            joints=JointsStream.parse(obj.get("joints", {}), key_path(path, "joints")),
            audio=AudioStream.parse(obj.get("audio", {}), key_path(path, "audio")),
        )


@dataclass(frozen=True)
class NaoBridgeConfig(JsonConfig):
    """Which robot and what to stream (specs/config.md). Defaults to the offline fake."""

    backend: Backend = "fake"
    robot: RobotSettings = field(default_factory=RobotSettings)
    streams: StreamSettings = field(default_factory=StreamSettings)

    def __post_init__(self) -> None:
        _require(
            self.backend in BACKENDS,
            f"backend must be one of {', '.join(map(repr, BACKENDS))}, got {self.backend!r}",
        )
        _require(
            self.backend != "real" or bool(self.robot.ip),
            "robot.ip is required for the real backend",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        obj = read_object(data, path)
        check_keys(obj, ("backend", "robot", "streams"), path)
        return build(
            cls,
            path,
            backend=read_choice(obj, "backend", "fake", BACKENDS, path),
            robot=RobotSettings.parse(obj.get("robot", {}), key_path(path, "robot")),
            streams=StreamSettings.parse(
                obj.get("streams", {}), key_path(path, "streams")
            ),
        )
