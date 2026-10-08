"""PLC 通信の共通インターフェース。

実機（slmp.SlmpPlcClient）とモック（mock.MockPlcClient）を差し替えられるよう、
指令処理と GUI はこのモジュールの PlcClient だけを使う。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from fx5s_commander.devices import Device


class PlcError(Exception):
    """PLC との通信に失敗した（接続失敗、タイムアウト、PLC からのエラー応答など）。"""


class DeviceNotAllowedError(Exception):
    """書き込みを許可していないデバイスへ書き込もうとした。"""


class PlcClient(Protocol):
    @property
    def is_connected(self) -> bool: ...

    def connect(self) -> None:
        """接続する。失敗したら PlcError。"""
        ...

    def close(self) -> None:
        """切断する。未接続でもエラーにしない。"""
        ...

    def read_bit(self, device: Device) -> bool: ...

    def write_bit(self, device: Device, value: bool) -> None: ...


class GuardedPlcClient:
    """許可リストにあるデバイスにだけ書き込めるようにするラッパー。

    設定ミスやコードの不具合で想定外のデバイスへ書き込まないよう、通信層の直前で止める。
    """

    def __init__(self, inner: PlcClient, allowed_writes: Iterable[Device]) -> None:
        self._inner = inner
        self._allowed_writes = frozenset(allowed_writes)

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def connect(self) -> None:
        self._inner.connect()

    def close(self) -> None:
        self._inner.close()

    def read_bit(self, device: Device) -> bool:
        return self._inner.read_bit(device)

    def write_bit(self, device: Device, value: bool) -> None:
        if device not in self._allowed_writes:
            raise DeviceNotAllowedError(f"{device} への書き込みは許可されていません")
        self._inner.write_bit(device, value)
