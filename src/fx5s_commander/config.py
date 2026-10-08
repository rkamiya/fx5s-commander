"""設定ファイル（TOML）の読み込みと検証。書式は config.example.toml を参照。"""

from __future__ import annotations

import ipaddress
import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fx5s_commander.commands import Command
from fx5s_commander.devices import Device, parse_device
from fx5s_commander.monitor import Lamp

PLC_TYPES = ("Q", "L", "QnA", "iQ-L", "iQ-R")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ConnectionConfig:
    host: str = "192.168.1.20"
    port: int = 5000
    plc_type: str = "L"
    timeout_sec: float = 2.0
    mock: bool = False
    """True なら実機に接続せず、モック PLC を使う。"""

    @property
    def label(self) -> str:
        """画面やログに出す接続先の表記。"""
        return "モック PLC" if self.mock else f"{self.host}:{self.port}"


@dataclass(frozen=True)
class HandshakeConfig:
    ack_timeout_sec: float = 1.0
    poll_interval_sec: float = 0.05


DEFAULT_DEVICES = {
    Command.ON: Device("M", 100),
    Command.OFF: Device("M", 101),
    Command.STOP: Device("M", 102),
}


DEFAULT_LAMPS = {
    Lamp.RUNNING: Device("M", 300),
    Lamp.STOPPED: Device("M", 301),
}


@dataclass(frozen=True)
class MonitorConfig:
    interval_sec: float = 0.5
    """ランプを読み出す間隔（秒）。"""


@dataclass(frozen=True)
class AppConfig:
    connection: ConnectionConfig
    devices: dict[Command, Device]
    """各指令で書き込むリレー。"""
    lamps: dict[Lamp, Device]
    """各ランプで読み出すリレー。"""
    handshake: HandshakeConfig
    monitor: MonitorConfig


def default_config() -> AppConfig:
    return AppConfig(
        ConnectionConfig(),
        dict(DEFAULT_DEVICES),
        dict(DEFAULT_LAMPS),
        HandshakeConfig(),
        MonitorConfig(),
    )


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"設定ファイルを読み込めません: {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"設定ファイルの書式が正しくありません: {path}: {e}") from e
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> AppConfig:
    defaults = default_config()

    conn = _section(data, "connection")
    connection = ConnectionConfig(
        host=_get(conn, "connection.host", str, defaults.connection.host),
        port=_get(conn, "connection.port", int, defaults.connection.port),
        plc_type=_get(conn, "connection.plc_type", str, defaults.connection.plc_type),
        timeout_sec=_get(conn, "connection.timeout_sec", float, defaults.connection.timeout_sec),
        mock=_get(conn, "connection.mock", bool, defaults.connection.mock),
    )
    validate_connection(connection)

    dev = _section(data, "devices")
    command_texts = {
        command: _get(dev, f"devices.{command.value}", str, str(defaults.devices[command]))
        for command in Command
    }
    lmp = _section(data, "lamps")
    lamp_texts = {
        lamp: _get(lmp, f"lamps.{lamp.value}", str, str(defaults.lamps[lamp])) for lamp in Lamp
    }
    try:
        devices, lamps = parse_relays(command_texts, lamp_texts)
    except ConfigError as e:
        raise ConfigError(f"[devices] / [lamps] {e}") from e

    hs = _section(data, "handshake")
    handshake = HandshakeConfig(
        ack_timeout_sec=_get(
            hs, "handshake.ack_timeout_sec", float, defaults.handshake.ack_timeout_sec
        ),
        poll_interval_sec=_get(
            hs, "handshake.poll_interval_sec", float, defaults.handshake.poll_interval_sec
        ),
    )
    if handshake.ack_timeout_sec <= 0 or handshake.poll_interval_sec <= 0:
        raise ConfigError("handshake の時間は正の値で指定してください")

    mon = _section(data, "monitor")
    monitor = MonitorConfig(
        interval_sec=_get(mon, "monitor.interval_sec", float, defaults.monitor.interval_sec)
    )
    if monitor.interval_sec < 0.1:
        raise ConfigError("monitor.interval_sec は 0.1 以上で指定してください")

    return AppConfig(connection, devices, lamps, handshake, monitor)


def parse_relays(
    command_texts: Mapping[Command, str], lamp_texts: Mapping[Lamp, str]
) -> tuple[dict[Command, Device], dict[Lamp, Device]]:
    """指令用とランプ用のリレー（'M100' など）を検証して変換する。

    M 以外や、同じリレーを複数の用途に割り当てた場合は ConfigError。
    """
    devices: dict[Command, Device] = {}
    for command in Command:
        devices[command] = _parse_relay(command_texts[command], command.label)
    lamps: dict[Lamp, Device] = {}
    for lamp in Lamp:
        lamps[lamp] = _parse_relay(lamp_texts[lamp], f"{lamp.label}ランプ")
    used = [*devices.values(), *lamps.values()]
    if len(set(used)) != len(used):
        raise ConfigError("同じリレーが複数の用途に割り当てられています")
    return devices, lamps


def _parse_relay(text: str, name: str) -> Device:
    try:
        return parse_device(text)
    except ValueError as e:
        raise ConfigError(f"{name}: {e}") from e


def validate_connection(connection: ConnectionConfig) -> None:
    try:
        # pymcprotocol は IPv4 のみ対応
        ipaddress.IPv4Address(connection.host)
    except ValueError as e:
        raise ConfigError(f"IP アドレスの形式が正しくありません: {connection.host!r}") from e
    if not 1 <= connection.port <= 65535:
        raise ConfigError(f"ポート番号は 1〜65535 で指定してください: {connection.port}")
    if connection.plc_type not in PLC_TYPES:
        raise ConfigError(f"connection.plc_type は {', '.join(PLC_TYPES)} のいずれかです")
    if connection.timeout_sec <= 0:
        raise ConfigError("connection.timeout_sec は正の値で指定してください")


def save_config(path: Path, config: AppConfig) -> None:
    """設定をファイルに保存する。ファイル内のコメントは残らない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dump_config(config), encoding="utf-8")
    os.replace(tmp, path)


def dump_config(config: AppConfig) -> str:
    conn, hs = config.connection, config.handshake
    lines = [
        "# FX5S Commander の設定（アプリの設定画面から保存したもの）",
        "# 各項目の説明は config.example.toml を参照",
        "",
        "[connection]",
        f"host = {json.dumps(conn.host)}",
        f"port = {conn.port}",
        f"plc_type = {json.dumps(conn.plc_type)}",
        f"timeout_sec = {conn.timeout_sec!r}",
        f"mock = {'true' if conn.mock else 'false'}",
        "",
        "[devices]",
        *(f'{command.value} = "{device}"' for command, device in config.devices.items()),
        "",
        "[lamps]",
        *(f'{lamp.value} = "{device}"' for lamp, device in config.lamps.items()),
        "",
        "[handshake]",
        f"ack_timeout_sec = {hs.ack_timeout_sec!r}",
        f"poll_interval_sec = {hs.poll_interval_sec!r}",
        "",
        "[monitor]",
        f"interval_sec = {config.monitor.interval_sec!r}",
    ]
    return "\n".join(lines) + "\n"


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] はテーブルで指定してください")
    return section


def _get(section: dict[str, Any], key: str, type_: type, default: Any) -> Any:
    value = section.get(key.rsplit(".", 1)[1], default)
    # TOML の整数は float の項目にも書けるようにする（bool は int の派生なので除外）
    if type_ is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, type_) or (type_ is not bool and isinstance(value, bool)):
        raise ConfigError(f"{key} の型が正しくありません（{type_.__name__} を指定してください）")
    return value
