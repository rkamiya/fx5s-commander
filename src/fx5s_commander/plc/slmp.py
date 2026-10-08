"""pymcprotocol を使った SLMP（3E フレーム、バイナリ）クライアント。

pymcprotocol の FX5S 実機での動作は未検証。互換性に問題があれば、このモジュールだけを
差し替える（自前の SLMP 実装など）ことで対応できるようにしている。
"""

from __future__ import annotations

import logging

from fx5s_commander.devices import Device
from fx5s_commander.plc.client import PlcError

logger = logging.getLogger(__name__)


class SlmpPlcClient:
    def __init__(self, host: str, port: int, *, plc_type: str, timeout_sec: float) -> None:
        self._host = host
        self._port = port
        self._plc_type = plc_type
        self._timeout_sec = timeout_sec
        self._plc = None

    @property
    def is_connected(self) -> bool:
        return self._plc is not None

    def connect(self) -> None:
        if self._plc is not None:
            return
        import pymcprotocol

        plc = pymcprotocol.Type3E(plctype=self._plc_type)
        plc.soc_timeout = self._timeout_sec
        # pymcprotocol は失敗時に socket の例外や素の Exception などを投げるため、まとめて捕まえる
        try:
            plc.setaccessopt(commtype="binary")
            plc.connect(self._host, self._port)
        except Exception as e:
            raise PlcError(f"{self._host}:{self._port} に接続できません: {e}") from e
        self._plc = plc
        logger.info("PLC に接続しました: %s:%s", self._host, self._port)

    def close(self) -> None:
        plc, self._plc = self._plc, None
        if plc is None:
            return
        try:
            plc.close()
        except Exception:
            logger.debug("切断時のエラーを無視しました", exc_info=True)
        logger.info("PLC から切断しました")

    def read_bit(self, device: Device) -> bool:
        plc = self._require_connection()
        try:
            values = plc.batchread_bitunits(headdevice=str(device), readsize=1)
        except Exception as e:
            self.close()
            raise PlcError(f"{device} の読み取りに失敗しました: {e}") from e
        return bool(values[0])

    def write_bit(self, device: Device, value: bool) -> None:
        plc = self._require_connection()
        try:
            plc.batchwrite_bitunits(headdevice=str(device), values=[1 if value else 0])
        except Exception as e:
            self.close()
            raise PlcError(f"{device} への書き込みに失敗しました: {e}") from e

    def _require_connection(self):
        if self._plc is None:
            raise PlcError("PLC に接続していません")
        return self._plc
