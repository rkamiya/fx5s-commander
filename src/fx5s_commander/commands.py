"""ON / OFF / 停止要求の指令を PLC へ送る処理。

送信方式は「PC が M を ON にする → ラダーが処理後に M を OFF に戻す → PC が OFF を確認する」
というハンドシェイク（docs/design.md の方式 B）。PC が M を ON にしただけでは成功とせず、
PLC が受け付けたことまで確認する。ただし受付確認は設備が実際に動いたことを意味しない。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from fx5s_commander.devices import Device
from fx5s_commander.plc.client import PlcClient, PlcError

logger = logging.getLogger(__name__)


class Command(Enum):
    ON = "on"
    OFF = "off"
    STOP = "stop"

    @property
    def label(self) -> str:
        # 画面表示名。「停止要求」の名称は要調整（仕様 4.1）
        return {Command.ON: "ON", Command.OFF: "OFF", Command.STOP: "停止要求"}[self]


class Outcome(Enum):
    ACCEPTED = "accepted"
    """PLC が M を OFF に戻した（指令を受け付けた）。"""
    NOT_ACCEPTED = "not_accepted"
    """時間内に PLC が受け付けなかったため、PC 側で M を OFF に戻して取り消した。"""
    BUSY = "busy"
    """M が既に ON だった（前回の指令が PLC で未処理）ため送信しなかった。"""
    ERROR = "error"
    """通信エラー。"""


@dataclass(frozen=True)
class CommandResult:
    command: Command
    device: Device
    outcome: Outcome
    message: str
    elapsed_sec: float


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str


class CommandSender:
    """PlcClient を使って指令を 1 件ずつ送る。スレッドセーフではない。"""

    def __init__(
        self,
        client: PlcClient,
        devices: Mapping[Command, Device],
        *,
        ack_timeout_sec: float,
        poll_interval_sec: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._devices = dict(devices)
        self._ack_timeout_sec = ack_timeout_sec
        self._poll_interval_sec = poll_interval_sec
        self._clock = clock
        self._sleep = sleep

    def device_for(self, command: Command) -> Device:
        return self._devices[command]

    def send(self, command: Command) -> CommandResult:
        device = self._devices[command]
        start = self._clock()

        def finish(outcome: Outcome, message: str) -> CommandResult:
            result = CommandResult(command, device, outcome, message, self._clock() - start)
            level = logging.INFO if outcome is Outcome.ACCEPTED else logging.WARNING
            logger.log(level, "%s (%s): %s - %s", command.label, device, outcome.value, message)
            return result

        try:
            if not self._client.is_connected:
                self._client.connect()
            if self._client.read_bit(device):
                return finish(
                    Outcome.BUSY,
                    f"{device} が既に ON です。前回の指令が PLC で未処理のため送信しませんでした。",
                )
            self._client.write_bit(device, True)
        except PlcError as e:
            self._client.close()
            return finish(Outcome.ERROR, f"送信できませんでした: {e}")

        # ここから先で通信が切れると、M が ON のまま PLC に残る可能性がある
        try:
            deadline = self._clock() + self._ack_timeout_sec
            while self._client.read_bit(device):
                if self._clock() >= deadline:
                    self._client.write_bit(device, False)
                    return finish(
                        Outcome.NOT_ACCEPTED,
                        f"{self._ack_timeout_sec:g} 秒以内に PLC が {device} を OFF に"
                        "戻さなかったため、指令を取り消しました。"
                        "ラダーの RST 処理を確認してください。",
                    )
                self._sleep(self._poll_interval_sec)
        except PlcError as e:
            self._client.close()
            return finish(
                Outcome.ERROR,
                f"{device} を ON にした後に通信エラーが発生しました。"
                f"PLC で指令が実行された可能性があります: {e}",
            )

        return finish(
            Outcome.ACCEPTED,
            f"{command.label} 指令を PLC が受け付けました（設備の動作は別途確認してください）。",
        )

    def set_client(self, client: PlcClient) -> None:
        """接続先を切り替える。今の接続は閉じる。"""
        self._client.close()
        self._client = client

    def close(self) -> None:
        self._client.close()


def check_connection(client: PlcClient, devices: Iterable[Device]) -> CheckResult:
    """接続して指定のデバイスを読み取り、現在の状態を返す。書き込みはしない。"""
    try:
        if not client.is_connected:
            client.connect()
        states = [f"{device}={'ON' if client.read_bit(device) else 'OFF'}" for device in devices]
    except PlcError as e:
        client.close()
        logger.warning("接続確認に失敗: %s", e)
        return CheckResult(False, f"接続確認に失敗しました: {e}")
    logger.info("接続確認 OK: %s", ", ".join(states))
    return CheckResult(True, f"接続 OK（{', '.join(states)}）")
