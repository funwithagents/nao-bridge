"""NaoqiBridgeConfig and the server configs (specs/config.md): defaults, the loader trio,
and every validation error naming its key path."""

import json
import sys
from pathlib import Path

import pytest
from naoqi_sim import NaoqiSimConfig
from naoqi_viewer import NaoqiViewerConfig

from naoqi_bridge.config import (
    AudioStream,
    CameraStream,
    CameraStreams,
    ConfigError,
    JointsStream,
    JsonConfig,
    NaoqiBridgeConfig,
    RobotSettings,
    SimSettings,
    StreamSettings,
    ViewerSettings,
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
        config.streams.joints.enabled
        or config.streams.audio.enabled
        or config.streams.cameras.top.enabled
        or config.streams.cameras.bottom.enabled
    )
    # A camera, once enabled, asks for QVGA at 10 fps unless told otherwise.
    assert config.streams.cameras.top == CameraStream(
        enabled=False, resolution="qvga", fps=10
    )
    assert NaoqiBridgeConfig.from_dict({}) == config


@pytest.mark.parametrize(
    "block",
    [
        RobotSettings,
        JointsStream,
        AudioStream,
        CameraStream,
        CameraStreams,
        StreamSettings,
        SimSettings,
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
            "robot": {"ip": "192.168.1.42", "port": 9600, "connect_timeout_s": 2.5},
            "streams": {
                "joints": {"enabled": True, "period_s": 0.5},
                "audio": {"enabled": True, "channel": "rear"},
                "cameras": {
                    "top": {"enabled": True, "resolution": "vga", "fps": 15},
                    "bottom": {"enabled": True, "resolution": "4vga", "fps": 1},
                },
            },
        }
    )
    assert config.robot == RobotSettings(
        ip="192.168.1.42", port=9600, connect_timeout_s=2.5
    )
    assert config.streams.joints == JointsStream(enabled=True, period_s=0.5)
    assert config.streams.audio == AudioStream(enabled=True, channel="rear")
    assert config.streams.cameras == CameraStreams(
        top=CameraStream(enabled=True, resolution="vga", fps=15),
        bottom=CameraStream(enabled=True, resolution="4vga", fps=1),
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"backend": "mars"}, "backend must be one of 'real', 'fake', 'sim'"),
        (
            {"sim": {"spawn": "sometimes"}},
            "sim.spawn must be one of 'never', 'auto', 'always'",
        ),
        ({"sim": {"version": "2.1"}}, "unknown key 'sim.version'"),
        ({"backend": "real"}, "robot.ip is required for the real backend"),
        ({"robot": {"port": 0}}, "robot.port must be a positive integer"),
        ({"robot": {"port": "9559"}}, "robot.port must be an integer"),
        # Gone since libqi 3.1.8: the connection makes one attempt.
        ({"robot": {"connect_tries": 3}}, "unknown key 'robot.connect_tries'"),
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
        (  # touch has no switch: a config from before that rule says so at load
            {"streams": {"touch": {"enabled": True}}},
            "unknown key 'streams.touch'",
        ),
        ({"streams": {"video": {}}}, "unknown key 'streams.video'"),
        (
            {"streams": {"cameras": {"top": {"resolution": "hd"}}}},
            "streams.cameras.top.resolution must be one of 'qqvga', 'qvga'",
        ),
        (
            {"streams": {"cameras": {"bottom": {"fps": 0}}}},
            "streams.cameras.bottom.fps must be an integer from 1 to 30",
        ),
        (
            {"streams": {"cameras": {"bottom": {"fps": 31}}}},
            "streams.cameras.bottom.fps must be an integer from 1 to 30",
        ),
        (
            {"streams": {"cameras": {"bottom": {"fps": 2.5}}}},
            "streams.cameras.bottom.fps must be an integer",
        ),
        (
            {"streams": {"cameras": {"bottom": {"fps": "10"}}}},
            "streams.cameras.bottom.fps must be an integer",
        ),
        (
            {"streams": {"cameras": {"top": {"colorspace": "rgb"}}}},
            "unknown key 'streams.cameras.top.colorspace'",
        ),
        (
            {"streams": {"cameras": {"front": {}}}},
            "unknown key 'streams.cameras.front'",
        ),
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
    with pytest.raises(ConfigError, match="fps"):
        CameraStream(fps=60)


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
        {"bridge": {"streams": {"joints": {"enabled": True}}}, "server": {"port": 9000}}
    )
    assert config.server.port == 9000
    assert config.server.host == ""  # the default: the LAN IP, found at start
    assert config.bridge.streams.joints.enabled
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


# region The sim block (specs/config.md "The `sim` block")


def test_a_naoqi_sim_config_pastes_in_as_sim_config():
    naoqi_sim_file = {
        "naoqi": {"version": "2.8", "ready_timeout_s": 60},
        "viewer": {"headless": True, "variant": "placeholder"},
        "video_input": {"source": "render"},
        "audio_output": {"mode": "silent"},
        "audio_input": {"source": "fake"},
    }
    config = NaoqiBridgeConfig.from_dict(
        {"backend": "sim", "sim": {"spawn": "never", "config": naoqi_sim_file}}
    )
    assert config.sim.spawn == "never"
    # naoqi-sim reads it exactly as its own CLI would read the file.
    assert config.sim.config == NaoqiSimConfig.from_dict(naoqi_sim_file)


def test_the_sim_backend_alone_borrows_or_starts_naoqi_sims_defaults():
    config = NaoqiBridgeConfig.from_dict({"backend": "sim"})
    assert config.sim == SimSettings(spawn="auto", config=None)
    assert NaoqiBridgeConfig(backend="sim") == config


def test_naoqi_sims_own_errors_come_back_under_sim_config():
    with pytest.raises(ConfigError) as caught:
        NaoqiBridgeConfig.from_dict(
            {"backend": "sim", "sim": {"config": {"viewer": {"variant": "shiny"}}}}
        )
    assert caught.value.key == "sim.config.viewer.variant"
    with pytest.raises(ConfigError) as caught:
        NaoqiBridgeConfig.from_dict({"sim": {"config": {"naoqi": {"versio": "2.1"}}}})
    assert caught.value.key.startswith("sim.config")


def test_a_sim_block_on_another_backend_is_validated_but_unused():
    config = NaoqiBridgeConfig.from_dict(
        {
            "backend": "fake",
            "sim": {"spawn": "always", "config": {"naoqi": {"version": "2.8"}}},
        }
    )
    assert config.backend == "fake"
    with pytest.raises(ConfigError, match="sim.config.naoqi.version"):
        NaoqiBridgeConfig.from_dict({"sim": {"config": {"naoqi": {"version": "3.0"}}}})


def test_without_naoqi_sim_only_the_sim_backend_is_refused(
    monkeypatch: pytest.MonkeyPatch,
):
    # A platform without the [sim] extra (no qi wheel): naoqi-sim can't be imported.
    monkeypatch.setitem(sys.modules, "naoqi_sim.config", None)
    with pytest.raises(ConfigError, match=r"naoqi-bridge\[sim\]") as caught:
        NaoqiBridgeConfig.from_dict({"backend": "sim"})
    assert caught.value.key == "backend"
    # A file that switches backends still loads; its sim.config stays unchecked.
    config = NaoqiBridgeConfig.from_dict(
        {"backend": "fake", "sim": {"config": {"naoqi": {"version": "2.1"}}}}
    )
    assert config.sim.config is None


# endregion

# region The viewer block (specs/viewer.md "Config: the `viewer` block")

REAL = {"backend": "real", "robot": {"ip": "192.168.1.42"}}


def test_a_naoqi_viewer_config_passes_through_as_viewer_config():
    block = {"ghost": True, "naoqi": {"rate_hz": 25}, "world": {"scene": "table"}}
    config = NaoqiBridgeConfig.from_dict(
        {**REAL, "viewer": {"enabled": True, "config": block}}
    )
    assert config.viewer == ViewerSettings(
        enabled=True, config=NaoqiViewerConfig.from_dict(block)
    )
    assert NaoqiBridgeConfig.from_dict({}).viewer == ViewerSettings(False, None)


@pytest.mark.parametrize(
    ("block", "key"),
    [
        ({"mode": "mirror"}, "viewer.config.mode"),
        ({"headless": False}, "viewer.config.headless"),
        ({"naoqi": {"url": "tcp://10.0.0.2:9559"}}, "viewer.config.naoqi.url"),
    ],
)
def test_what_the_bridge_sets_is_refused_in_viewer_config(block: dict, key: str):
    # Even a value the bridge would set itself: the robot decides it, not the file.
    with pytest.raises(ConfigError, match="is set by the bridge") as caught:
        NaoqiBridgeConfig.from_dict({**REAL, "viewer": {"config": block}})
    assert caught.value.key == key


def test_naoqi_viewers_own_errors_come_back_under_viewer_config():
    with pytest.raises(ConfigError) as caught:
        NaoqiBridgeConfig.from_dict({"viewer": {"config": {"world": {"variant": "x"}}}})
    assert caught.value.key == "viewer.config.world.variant"
    with pytest.raises(ConfigError, match="unknown key"):
        NaoqiBridgeConfig.from_dict({"viewer": {"config": {"gost": True}}})
    with pytest.raises(ConfigError) as caught:
        NaoqiBridgeConfig.from_dict({"viewer": {"enabled": "yes"}})
    assert caught.value.key == "viewer.enabled"


@pytest.mark.parametrize("backend", ["real", "sim"])
def test_without_naoqi_viewer_an_enabled_viewer_is_refused_where_it_would_open(
    monkeypatch: pytest.MonkeyPatch, backend: str
):
    monkeypatch.setitem(sys.modules, "naoqi_viewer.config", None)
    data = {**REAL, "backend": backend, "viewer": {"enabled": True}}
    with pytest.raises(ConfigError, match=r"naoqi-bridge\[viewer\]") as caught:
        NaoqiBridgeConfig.from_dict(data)
    assert caught.value.key == "viewer.enabled"


def test_without_naoqi_viewer_a_file_that_switches_backends_still_loads(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "naoqi_viewer.config", None)
    on_fake = NaoqiBridgeConfig.from_dict(
        {"viewer": {"enabled": True, "config": {"ghost": True}}}
    )
    assert on_fake.viewer == ViewerSettings(enabled=True, config=None)
    disabled = NaoqiBridgeConfig.from_dict(
        {**REAL, "viewer": {"enabled": False, "config": {"ghost": True}}}
    )
    assert disabled.viewer.config is None


# endregion


@pytest.mark.parametrize("name", ["mcp-fake", "mcp-real", "mcp-sim"])
def test_mcp_examples_load(name: str):
    NaoqiMcpServerConfig.from_json_file(EXAMPLES / f"{name}.json")


@pytest.mark.parametrize("name", ["websocket-fake", "websocket-real", "websocket-sim"])
def test_websocket_examples_load_with_every_stream(name: str):
    streams = NaoqiWebsocketServerConfig.from_json_file(
        EXAMPLES / f"{name}.json"
    ).bridge.streams
    assert streams.joints.enabled and streams.audio.enabled
    assert streams.cameras.top == CameraStream(enabled=True, resolution="qvga", fps=10)
    assert not streams.cameras.bottom.enabled
