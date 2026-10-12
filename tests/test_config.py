"""NaoqiBridgeConfig and the server configs (specs/config.md): defaults, the loader trio,
and every validation error naming its key path."""

import json
from pathlib import Path

import pytest

from naoqi_bridge.config import (
    AudioStream,
    ConfigError,
    JointsStream,
    JsonConfig,
    NaoqiBridgeConfig,
    RobotSettings,
    StreamSettings,
    TouchStream,
)
from naoqi_bridge.naoqi_mcp_server import McpServerSettings, NaoqiMcpServerConfig
from naoqi_bridge.naoqi_websocket_server import (
    NaoqiWebsocketServerConfig,
    WebsocketServerSettings,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "configs"


def test_the_default_config_is_the_offline_fake_with_no_streams():
    config = NaoqiBridgeConfig()
    assert config.backend == "fake"
    assert not (
        config.streams.touch.enabled
        or config.streams.joints.enabled
        or config.streams.audio.enabled
    )
    assert NaoqiBridgeConfig.from_dict({}) == config


@pytest.mark.parametrize(
    "block",
    [
        RobotSettings,
        TouchStream,
        JointsStream,
        AudioStream,
        StreamSettings,
        NaoqiBridgeConfig,
        McpServerSettings,
        WebsocketServerSettings,
        NaoqiMcpServerConfig,
        NaoqiWebsocketServerConfig,
    ],
)
def test_an_empty_object_loads_as_the_blocks_own_defaults(block: type[JsonConfig]):
    # The loader has no defaults of its own: an absent key is the dataclass's default.
    assert block.from_dict({}) == block()


def test_a_full_config_loads_every_field():
    config = NaoqiBridgeConfig.from_dict(
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
    assert config.robot.connect_timeout_s == 5.0  # the default
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
            {"robot": {"connect_timeout_s": 0}},
            "robot.connect_timeout_s must be a positive",
        ),
        (
            {"robot": {"connect_timeout_s": float("inf")}},
            "robot.connect_timeout_s must be a positive",
        ),
        (
            {"robot": {"connect_timeout_s": "5s"}},
            "robot.connect_timeout_s must be a number",
        ),
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
        NaoqiBridgeConfig.from_dict(data)


def test_a_config_error_carries_its_key_path():
    with pytest.raises(ConfigError) as caught:
        NaoqiWebsocketServerConfig.from_dict(
            {"bridge": {"streams": {"joints": {"period_s": 0}}}}
        )
    assert caught.value.key == "bridge.streams.joints.period_s"
    assert caught.value.detail.startswith("must be a positive")
    assert str(caught.value) == f"{caught.value.key} {caught.value.detail}"


def test_direct_construction_validates_too():
    with pytest.raises(ConfigError, match="robot.ip is required"):
        NaoqiBridgeConfig(backend="real")
    with pytest.raises(ConfigError, match="period_s"):
        JointsStream(period_s=0)


def test_a_robot_block_on_fake_is_validated_but_unused():
    config = NaoqiBridgeConfig.from_dict(
        {"backend": "fake", "robot": {"ip": "10.0.0.5"}}
    )
    assert config.backend == "fake" and config.robot.ip == "10.0.0.5"
    with pytest.raises(ConfigError, match="robot.port"):
        NaoqiBridgeConfig.from_dict({"backend": "fake", "robot": {"port": -1}})


def test_json_loaders(tmp_path: Path):
    text = json.dumps({"backend": "real", "robot": {"ip": "10.0.0.5"}})
    assert NaoqiBridgeConfig.from_json(text).robot.ip == "10.0.0.5"
    with pytest.raises(ConfigError, match="invalid JSON"):
        NaoqiBridgeConfig.from_json("{backend: real}")

    file = tmp_path / "nao.json"
    file.write_text(text)
    assert NaoqiBridgeConfig.from_json_file(file).backend == "real"
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    with pytest.raises(ConfigError, match="broken.json"):
        NaoqiBridgeConfig.from_json_file(broken)
    with pytest.raises(ConfigError, match="cannot read config file"):
        NaoqiBridgeConfig.from_json_file(tmp_path / "missing.json")


def test_server_configs_nest_the_bridge_and_their_own_settings():
    config = NaoqiWebsocketServerConfig.from_dict(
        {"bridge": {"streams": {"touch": {"enabled": True}}}, "server": {"port": 9000}}
    )
    assert config.server.port == 9000
    assert config.server.host == ""  # the default: the LAN IP, found at start
    assert config.bridge.streams.touch.enabled
    local = NaoqiWebsocketServerConfig.from_dict(
        {"server": {"host": "127.0.0.1", "port": 0}}
    )
    assert (local.server.host, local.server.port) == ("127.0.0.1", 0)
    assert NaoqiMcpServerConfig.from_dict({}).server.transport == "stdio"


@pytest.mark.parametrize(
    ("factory", "data", "message"),
    [
        (
            NaoqiWebsocketServerConfig,
            {"server": {"port": 70000}},
            "server.port must be between",
        ),
        (
            NaoqiWebsocketServerConfig,
            {"server": {"host": 1}},
            "server.host must be a string",
        ),
        (
            NaoqiWebsocketServerConfig,
            {"bridge": {"backend": "real"}},
            "bridge.robot.ip is required",
        ),
        (NaoqiWebsocketServerConfig, {"port": 8002}, "unknown key 'port'"),
        (
            NaoqiMcpServerConfig,
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
    NaoqiMcpServerConfig.from_json_file(EXAMPLES / f"{name}.json")


@pytest.mark.parametrize("name", ["websocket-fake", "websocket-real"])
def test_websocket_examples_load_with_every_stream(name: str):
    streams = NaoqiWebsocketServerConfig.from_json_file(
        EXAMPLES / f"{name}.json"
    ).bridge.streams
    assert streams.touch.enabled and streams.joints.enabled and streams.audio.enabled
