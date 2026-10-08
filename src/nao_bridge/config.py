"""Bridge configuration: ``NaoBridgeConfig`` and its blocks (specs/config.md).

One declarative description of which robot to drive and what to stream from it, built
in code or loaded with the ``from_dict`` / ``from_json`` / ``from_json_file`` trio.
Invalid input raises ``ConfigError`` naming the offending key path. Each block checks
its own ranges on construction; the loaders also check shape, types and unknown keys.

A default is declared once, on the dataclass field: ``parse_block`` reads only the
keys present in the JSON and lets the dataclass apply its defaults for the rest. The
value readers (``as_*``), ``parse_block`` and the ``JsonConfig`` base are public so
configs that wrap a ``NaoBridgeConfig`` (the servers') validate the same way. This
module imports neither ``qi`` nor ``mcp`` nor ``websockets``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
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
    "Reader",
    "RobotSettings",
    "StreamSettings",
    "TouchStream",
    "as_bool",
    "as_choice",
    "as_int",
    "as_number",
    "as_str",
    "key_path",
    "parse_block",
]

type Backend = Literal["real", "fake"]
type AudioChannel = Literal["front", "rear", "left", "right"]
BACKENDS: tuple[Backend, ...] = ("real", "fake")
AUDIO_CHANNELS: tuple[AudioChannel, ...] = ("front", "rear", "left", "right")

# Turns a raw JSON value found at a key path into a field's value, or raises
# ``ConfigError``. A block's ``parse`` classmethod is one too.
type Reader[T] = Callable[[Any, str], T]


class ConfigError(ValueError):
    """A malformed configuration. ``key`` is the offending key path (empty when the
    error isn't about one key) and ``detail`` the complaint; ``str()`` joins them."""

    def __init__(self, detail: str, *, key: str = "") -> None:
        super().__init__(f"{key} {detail}" if key else detail)
        self.key = key
        self.detail = detail


def key_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


# region Value readers


def as_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"must be a boolean, got {value!r}", key=key)
    return value


def as_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"must be an integer, got {value!r}", key=key)
    return value


def as_number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"must be a number, got {value!r}", key=key)
    return float(value)


def as_str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"must be a string, got {value!r}", key=key)
    return value


def as_choice[C: str](choices: tuple[C, ...]) -> Reader[C]:
    def read(value: Any, key: str) -> C:
        for choice in choices:
            if value == choice:
                return choice
        expected = ", ".join(repr(c) for c in choices)
        raise ConfigError(f"must be one of {expected}, got {value!r}", key=key)

    return read


def parse_block[T](
    factory: Callable[..., T], data: Any, path: str, **readers: Reader[Any]
) -> T:
    """Build the block ``factory`` from the JSON object ``data`` found at ``path``.

    ``readers`` names the allowed keys and how to read each; a key that's absent is
    left to the dataclass default, an unknown one is an error. The block's own
    validation errors (``__post_init__``) are prefixed with ``path``.
    """
    if not isinstance(data, dict):
        raise ConfigError(
            f"must be an object, got {type(data).__name__}", key=path or "config"
        )
    obj: dict[str, Any] = data
    for key in obj:
        if key not in readers:
            raise ConfigError(
                f"unknown key {key_path(path, key)!r}; expected one of: "
                + ", ".join(readers)
            )
    kwargs = {
        name: reader(obj[name], key_path(path, name))
        for name, reader in readers.items()
        if name in obj
    }
    try:
        return factory(**kwargs)
    except ConfigError as e:
        raise ConfigError(e.detail, key=key_path(path, e.key)) from None


def _require(condition: bool, key: str, detail: str) -> None:
    if not condition:
        raise ConfigError(detail, key=key)


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
    # Per attempt: a host that doesn't answer would otherwise hold each attempt for
    # the OS TCP timeout (over a minute).
    connect_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        _require(self.port > 0, "port", f"must be a positive integer, got {self.port}")
        _require(
            self.connect_tries > 0,
            "connect_tries",
            f"must be a positive integer, got {self.connect_tries}",
        )
        _require(
            math.isfinite(self.connect_timeout_s) and self.connect_timeout_s > 0,
            "connect_timeout_s",
            f"must be a positive, finite number, got {self.connect_timeout_s}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls,
            data,
            path,
            ip=as_str,
            port=as_int,
            connect_tries=as_int,
            connect_timeout_s=as_number,
        )


@dataclass(frozen=True)
class TouchStream(JsonConfig):
    enabled: bool = False

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(cls, data, path, enabled=as_bool)


@dataclass(frozen=True)
class JointsStream(JsonConfig):
    enabled: bool = False
    period_s: float = 0.2

    def __post_init__(self) -> None:
        _require(
            math.isfinite(self.period_s) and self.period_s > 0,
            "period_s",
            f"must be a positive, finite number, got {self.period_s}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(cls, data, path, enabled=as_bool, period_s=as_number)


@dataclass(frozen=True)
class AudioStream(JsonConfig):
    enabled: bool = False
    channel: AudioChannel = "front"

    def __post_init__(self) -> None:
        _require(
            self.channel in AUDIO_CHANNELS,
            "channel",
            f"must be one of {', '.join(map(repr, AUDIO_CHANNELS))}, "
            f"got {self.channel!r}",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls, data, path, enabled=as_bool, channel=as_choice(AUDIO_CHANNELS)
        )


@dataclass(frozen=True)
class StreamSettings(JsonConfig):
    """Which robot streams the bridge subscribes to at ``start()``."""

    touch: TouchStream = field(default_factory=TouchStream)
    joints: JointsStream = field(default_factory=JointsStream)
    audio: AudioStream = field(default_factory=AudioStream)

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls,
            data,
            path,
            touch=TouchStream.parse,
            joints=JointsStream.parse,
            audio=AudioStream.parse,
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
            "backend",
            f"must be one of {', '.join(map(repr, BACKENDS))}, got {self.backend!r}",
        )
        _require(
            self.backend != "real" or bool(self.robot.ip),
            "robot.ip",
            "is required for the real backend",
        )

    @classmethod
    def parse(cls, data: Any, path: str) -> Self:
        return parse_block(
            cls,
            data,
            path,
            backend=as_choice(BACKENDS),
            robot=RobotSettings.parse,
            streams=StreamSettings.parse,
        )
