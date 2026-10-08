"""PLC デバイスの表現と検証。

PC から読み書きするデバイスを M（内部リレー）に限定する。X（物理入力）や Y（物理出力）、
D（データレジスタ）を誤って書き換えないよう、ここで受け付けるデバイスの種類と範囲を絞る。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# FX5S の M デバイスの既定点数は M0〜M7679。
# GX Works3 のデバイス設定で点数を変えている場合は、実機に合わせて見直す。
M_DEVICE_MAX = 7679

_DEVICE_PATTERN = re.compile(r"^\s*([A-Za-z]+)(\d+)\s*$")


@dataclass(frozen=True, order=True)
class Device:
    kind: str
    number: int

    def __str__(self) -> str:
        return f"{self.kind}{self.number}"


def parse_device(text: str) -> Device:
    """'M100' のような文字列を Device に変換する。M デバイス以外は ValueError。"""
    match = _DEVICE_PATTERN.match(text)
    if match is None:
        raise ValueError(f"デバイスの形式が正しくありません: {text!r}")
    kind, number_text = match.group(1).upper(), match.group(2)
    if kind != "M":
        raise ValueError(f"指定できるのは M デバイスのみです: {text!r}")
    number = int(number_text)
    if number > M_DEVICE_MAX:
        raise ValueError(f"M デバイスの範囲（M0〜M{M_DEVICE_MAX}）外です: {text!r}")
    return Device(kind, number)
