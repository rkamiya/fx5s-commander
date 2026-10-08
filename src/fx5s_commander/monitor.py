"""ランプ表示用の状態読み出し。

稼働中・停止中などの状態を PLC の内部リレーから読み取る。書き込みはしない。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from fx5s_commander.devices import Device
from fx5s_commander.plc.client import PlcClient, PlcError

logger = logging.getLogger(__name__)


class Lamp(Enum):
    RUNNING = "running"
    STOPPED = "stopped"

    @property
    def label(self) -> str:
        return {Lamp.RUNNING: "稼働中", Lamp.STOPPED: "停止中"}[self]


@dataclass(frozen=True)
class LampReading:
    states: dict[Lamp, bool] | None
    """読み取れたときの各ランプの状態。読み取れなかったときは None。"""
    error: str | None = None


def read_lamps(client: PlcClient, lamps: Mapping[Lamp, Device]) -> LampReading:
    try:
        if not client.is_connected:
            client.connect()
        states = {lamp: client.read_bit(device) for lamp, device in lamps.items()}
    except PlcError as e:
        client.close()
        return LampReading(None, str(e))
    return LampReading(states)
