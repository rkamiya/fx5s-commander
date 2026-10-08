"""実機なしで開発・テストするための PLC モック。

ラダー側の「指令用 M が ON になったら処理して OFF に戻す」動作を ack_delay_sec で真似る。
ack_delay_sec=None にすると OFF に戻さない（ラダー未対応の PLC を想定）。
simulate_ladder() を使うと、指令に応じてランプ用の M も切り替わる。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from fx5s_commander.commands import Command
from fx5s_commander.devices import Device
from fx5s_commander.monitor import Lamp
from fx5s_commander.plc.client import PlcError


class MockPlcClient:
    def __init__(
        self,
        *,
        ack_delay_sec: float | None = 0.2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ack_delay_sec = ack_delay_sec
        self.fail_connect = False
        """True にすると connect() が失敗する。"""
        self.fail_io = False
        """True にすると read_bit() / write_bit() が失敗する。"""
        self.bits: dict[Device, bool] = {}
        self.writes: list[tuple[Device, bool]] = []
        self.on_ack: Callable[[Device], None] | None = None
        """PLC が指令用の M を OFF に戻した（受け付けた）ときに呼ばれる。"""
        self._clock = clock
        self._ack_at: dict[Device, float] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self.fail_connect:
            raise PlcError("モック: 接続に失敗しました")
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def read_bit(self, device: Device) -> bool:
        self._check_io()
        ack_at = self._ack_at.get(device)
        if ack_at is not None and self._clock() >= ack_at:
            self.bits[device] = False
            del self._ack_at[device]
            if self.on_ack is not None:
                self.on_ack(device)
        return self.bits.get(device, False)

    def write_bit(self, device: Device, value: bool) -> None:
        self._check_io()
        self.writes.append((device, value))
        self.bits[device] = value
        if value and self.ack_delay_sec is not None:
            self._ack_at[device] = self._clock() + self.ack_delay_sec
        else:
            self._ack_at.pop(device, None)

    def _check_io(self) -> None:
        if not self._connected:
            raise PlcError("モック: 接続していません")
        if self.fail_io:
            self._connected = False
            raise PlcError("モック: 通信エラー")


def simulate_ladder(
    plc: MockPlcClient, devices: Mapping[Command, Device], lamps: Mapping[Lamp, Device]
) -> None:
    """docs/ladder.md の回路例と同じように、指令に応じてランプ用の M を切り替える。"""
    commands = {device: command for command, device in devices.items()}

    def set_running(running: bool) -> None:
        plc.bits[lamps[Lamp.RUNNING]] = running
        plc.bits[lamps[Lamp.STOPPED]] = not running

    def on_ack(device: Device) -> None:
        command = commands.get(device)
        if command is not None:
            set_running(command is Command.ON)

    set_running(False)
    plc.on_ack = on_ack
