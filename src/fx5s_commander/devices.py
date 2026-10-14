"""PLC デバイスの表現と検証。

PC から読み書きするデバイスを、M（内部リレー）と文字列用の D（データレジスタ）に限定する。
X（物理入力）や Y（物理出力）を誤って書き換えないよう、ここで受け付けるデバイスの種類と範囲を絞る。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# FX5S の既定のデバイス点数。M は M0〜M7679、D は D0〜D7999。
# GX Works3 のデバイス設定で点数を変えている場合は、実機に合わせて見直す。
M_DEVICE_MAX = 7679
D_DEVICE_MAX = 7999

_DEVICE_PATTERN = re.compile(r"^\s*([A-Za-z]+)(\d+)\s*$")


@dataclass(frozen=True, order=True)
class Device:
    kind: str
    number: int

    def __str__(self) -> str:
        return f"{self.kind}{self.number}"

    def offset(self, count: int) -> Device:
        """count 個先のデバイス（D100.offset(15) は D115）。"""
        return Device(self.kind, self.number + count)


def parse_device(text: str) -> Device:
    """'M100' のような文字列を Device に変換する。M デバイス以外は ValueError。"""
    return _parse(text, "M", M_DEVICE_MAX)


def parse_word_device(text: str, *, words: int = 1) -> Device:
    """'D100' のような文字列を Device に変換する。D デバイス以外は ValueError。

    words を指定すると、先頭から words 点がすべて範囲内に収まるかも確かめる。
    """
    device = _parse(text, "D", D_DEVICE_MAX)
    last = device.offset(words - 1)
    if last.number > D_DEVICE_MAX:
        raise ValueError(
            f"{device}〜{last} は D デバイスの範囲（D0〜D{D_DEVICE_MAX}）を超えます: {text!r}"
        )
    return device


def _parse(text: str, kind: str, max_number: int) -> Device:
    match = _DEVICE_PATTERN.match(text)
    if match is None:
        raise ValueError(f"デバイスの形式が正しくありません: {text!r}")
    actual_kind, number_text = match.group(1).upper(), match.group(2)
    if actual_kind != kind:
        raise ValueError(f"指定できるのは {kind} デバイスのみです: {text!r}")
    number = int(number_text)
    if number > max_number:
        raise ValueError(f"{kind} デバイスの範囲（{kind}0〜{kind}{max_number}）外です: {text!r}")
    return Device(kind, number)
