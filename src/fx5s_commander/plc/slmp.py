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

    def read_words(self, head: Device, count: int) -> list[int]:
        plc = self._require_connection()
        try:
            values = plc.batchread_wordunits(headdevice=str(head), readsize=count)
        except Exception as e:
            self.close()
            raise PlcError(f"{head} からの読み取りに失敗しました: {e}") from e
        # pymcprotocol は符号付きで返すので、0〜0xFFFF に揃える
        return [value & 0xFFFF for value in values]

    def write_words(self, head: Device, values: list[int]) -> None:
        # 範囲外の値を変換すると別の値になって黙って書き込まれるので、先に止める
        invalid = [value for value in values if not 0 <= value <= 0xFFFF]
        if invalid:
            raise ValueError(f"ワードの値は 0〜0xFFFF で指定してください: {invalid}")
        plc = self._require_connection()
        # pymcprotocol は符号付きの値を受け取るので、0x8000 以上は負の値に直す
        signed = [value - 0x10000 if value >= 0x8000 else value for value in values]
        try:
            plc.batchwrite_wordunits(headdevice=str(head), values=signed)
        except Exception as e:
            self.close()
            raise PlcError(f"{head} への書き込みに失敗しました: {e}") from e

    def _require_connection(self):
        if self._plc is None:
            raise PlcError("PLC に接続していません")
        return self._plc
