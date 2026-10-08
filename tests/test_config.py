from pathlib import Path

import pytest

from fx5s_commander.commands import Command
from fx5s_commander.config import (
    ConfigError,
    default_config,
    dump_config,
    load_config,
    parse_config,
    parse_devices,
    save_config,
)
from fx5s_commander.devices import Device

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"


def test_empty_config_uses_defaults():
    assert parse_config({}) == default_config()


def test_example_file_matches_defaults():
    assert load_config(EXAMPLE) == default_config()


def test_overrides():
    config = parse_config(
        {
            "connection": {"host": "10.0.0.5", "port": 6000, "timeout_sec": 3, "mock": True},
            "devices": {"on": "M200", "off": "M201", "stop": "M202"},
            "handshake": {"ack_timeout_sec": 2},
        }
    )
    assert config.connection.host == "10.0.0.5"
    assert config.connection.port == 6000
    assert config.connection.timeout_sec == 3.0
    assert config.connection.mock is True
    assert config.devices[Command.STOP] == Device("M", 202)
    assert config.handshake.ack_timeout_sec == 2.0


@pytest.mark.parametrize(
    "data",
    [
        {"connection": {"port": 0}},
        {"connection": {"port": "5000"}},
        {"connection": {"host": ""}},
        {"connection": {"host": "plc.local"}},
        {"connection": {"host": "192.168.1.256"}},
        {"connection": {"plc_type": "FX5"}},
        {"connection": {"mock": "yes"}},
        {"connection": {"mock": 1}},
        {"connection": {"timeout_sec": 0}},
        {"devices": {"on": "Y0"}},
        {"devices": {"on": "M101"}},  # off と重複
        {"handshake": {"poll_interval_sec": -1}},
        {"handshake": {"ack_timeout_sec": True}},
        {"connection": "192.168.1.20"},
    ],
)
def test_invalid(data):
    with pytest.raises(ConfigError):
        parse_config(data)


def test_load_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")


def test_load_broken_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[connection\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_save_and_load_round_trip(tmp_path):
    config = parse_config(
        {
            "connection": {"host": "10.0.0.5", "port": 6000, "timeout_sec": 1.5, "mock": True},
            "devices": {"on": "M200", "off": "M201", "stop": "M202"},
            "handshake": {"ack_timeout_sec": 0.8, "poll_interval_sec": 0.02},
        }
    )
    path = tmp_path / "sub" / "config.toml"

    save_config(path, config)

    assert load_config(path) == config
    assert not (tmp_path / "sub" / "config.toml.tmp").exists()


def test_dump_default_is_loadable():
    import tomllib

    assert parse_config(tomllib.loads(dump_config(default_config()))) == default_config()


def test_parse_devices():
    devices = parse_devices({Command.ON: "m10", Command.OFF: "M11", Command.STOP: " M12 "})
    assert devices == {
        Command.ON: Device("M", 10),
        Command.OFF: Device("M", 11),
        Command.STOP: Device("M", 12),
    }


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        ({Command.ON: "Y0", Command.OFF: "M11", Command.STOP: "M12"}, "ON"),
        ({Command.ON: "M10", Command.OFF: "", Command.STOP: "M12"}, "OFF"),
        ({Command.ON: "M10", Command.OFF: "M11", Command.STOP: "M99999"}, "停止要求"),
        ({Command.ON: "M10", Command.OFF: "M10", Command.STOP: "M12"}, "複数"),
    ],
)
def test_parse_devices_invalid(texts, expected):
    with pytest.raises(ConfigError, match=expected):
        parse_devices(texts)
