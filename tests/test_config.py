"""NaoBridgeConfig and the server configs (specs/config.md): defaults, the loader trio,
and every validation error naming its key path."""

import json
from pathlib import Path

import pytest

from nao_bridge.config import (
    AudioStream,
    ConfigError,
    JointsStream,
    NaoBridgeConfig,
    RobotSettings,
)
from nao_bridge.nao_mcp_server import NaoMcpServerConfig
from nao_bridge.nao_websocket_server import NaoWebsocketServerConfig

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "configs"


def test_the_default_config_is_the_offline_fake_with_no_streams():
    config = NaoBridgeConfig()
    assert config.backend == "fake"
    assert not (
        config.streams.touch.enabled
        or config.streams.joints.enabled
        or config.streams.audio.enabled
    )
    assert NaoBridgeConfig.from_dict({}) == config


def test_a_full_config_loads_every_field():
    config = NaoBridgeConfig.from_dict(
        {
            "backend": "real",
            "robot": {"ip": "192.168.1.42", "port": 9600, "connect_tries": 3},
            "streams": {
                "touch": {"enabled": True},
                "joints": {"enabled": True, "period_s": 0.5},
                "audio": {"enabled": True, "channel": "rear"},
            },
        }
    )
    assert config.robot == RobotSettings(ip="192.168.1.42", port=9600, connect_tries=3)
    assert config.streams.joints == JointsStream(enabled=True, period_s=0.5)
    assert config.streams.audio == AudioStream(enabled=True, channel="rear")
    assert config.streams.touch.enabled


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"backend": "sim"}, "backend must be one of 'real', 'fake'"),
        ({"backend": "real"}, "robot.ip is required for the real backend"),
        ({"robot": {"port": 0}}, "robot.port must be a positive integer"),
        ({"robot": {"port": "9559"}}, "robot.port must be an integer"),
        ({"robot": {"connect_tries": True}}, "robot.connect_tries must be an integer"),
        ({"robot": {"adress": "x"}}, "unknown key 'robot.adress'"),
        (
            {"streams": {"joints": {"period_s": -1}}},
            "streams.joints.period_s must be a positive",
        ),
        (
            {"streams": {"joints": {"period_s": "fast"}}},
            "streams.joints.period_s must be a number",
        ),
        (
            {"streams": {"audio": {"channel": "all"}}},
            "streams.audio.channel must be one of",
        ),
        (
            {"streams": {"touch": {"enabled": "yes"}}},
            "streams.touch.enabled must be a boolean",
        ),
        ({"streams": {"video": {}}}, "unknown key 'streams.video'"),
        ({"streams": []}, "streams must be an object"),
        ([], "config must be an object"),
    ],
)
def test_invalid_configs_name_the_offending_key(data: object, message: str):
    with pytest.raises(ConfigError, match=message):
        NaoBridgeConfig.from_dict(data)


def test_direct_construction_validates_too():
    with pytest.raises(ConfigError, match="robot.ip is required"):
        NaoBridgeConfig(backend="real")
    with pytest.raises(ConfigError, match="period_s"):
        JointsStream(period_s=0)


def test_a_robot_block_on_fake_is_validated_but_unused():
    config = NaoBridgeConfig.from_dict({"backend": "fake", "robot": {"ip": "10.0.0.5"}})
    assert config.backend == "fake" and config.robot.ip == "10.0.0.5"
    with pytest.raises(ConfigError, match="robot.port"):
        NaoBridgeConfig.from_dict({"backend": "fake", "robot": {"port": -1}})


def test_json_loaders(tmp_path: Path):
    text = json.dumps({"backend": "real", "robot": {"ip": "10.0.0.5"}})
    assert NaoBridgeConfig.from_json(text).robot.ip == "10.0.0.5"
    with pytest.raises(ConfigError, match="invalid JSON"):
        NaoBridgeConfig.from_json("{backend: real}")

    file = tmp_path / "nao.json"
    file.write_text(text)
    assert NaoBridgeConfig.from_json_file(file).backend == "real"
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    with pytest.raises(ConfigError, match="broken.json"):
        NaoBridgeConfig.from_json_file(broken)
    with pytest.raises(ConfigError, match="cannot read config file"):
        NaoBridgeConfig.from_json_file(tmp_path / "missing.json")


def test_server_configs_nest_the_bridge_and_their_own_settings():
    config = NaoWebsocketServerConfig.from_dict(
        {"bridge": {"streams": {"touch": {"enabled": True}}}, "server": {"port": 9000}}
    )
    assert config.server.port == 9000
    assert config.bridge.streams.touch.enabled
    assert NaoMcpServerConfig.from_dict({}).server.transport == "stdio"


@pytest.mark.parametrize(
    ("factory", "data", "message"),
    [
        (
            NaoWebsocketServerConfig,
            {"server": {"port": 70000}},
            "server.port must be between",
        ),
        (
            NaoWebsocketServerConfig,
            {"bridge": {"backend": "real"}},
            "bridge.robot.ip is required",
        ),
        (NaoWebsocketServerConfig, {"port": 8002}, "unknown key 'port'"),
        (
            NaoMcpServerConfig,
            {"server": {"transport": "http"}},
            "server.transport must be one of",
        ),
    ],
)
def test_server_config_errors_carry_the_full_path(
    factory: type, data: object, message: str
):
    with pytest.raises(ConfigError, match=message):
        factory.from_dict(data)


@pytest.mark.parametrize("name", ["mcp-fake", "mcp-real"])
def test_mcp_examples_load(name: str):
    NaoMcpServerConfig.from_json_file(EXAMPLES / f"{name}.json")


@pytest.mark.parametrize("name", ["websocket-fake", "websocket-real"])
def test_websocket_examples_load_with_every_stream(name: str):
    streams = NaoWebsocketServerConfig.from_json_file(
        EXAMPLES / f"{name}.json"
    ).bridge.streams
    assert streams.touch.enabled and streams.joints.enabled and streams.audio.enabled
