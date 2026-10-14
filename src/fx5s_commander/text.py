"""文字列を D デバイスに ASCII で書き込む処理。

1 ワードに 2 文字を入れる。先の文字を下位バイト、次の文字を上位バイトにする
（GX Works3 で文字列を扱うときと同じ並び）。
例: "SOS" → D100 = H4F53（'S'=H53, 'O'=H4F）, D101 = H0053（'S' と終端の 0）

書き込むときは毎回 TEXT_WORDS 点すべてを書き、文字のない部分は 0 で埋める。
こうしないと、前に書いた長い文字列の後ろが残ってしまう。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fx5s_commander.devices import Device
from fx5s_commander.plc.client import PlcClient, PlcError

logger = logging.getLogger(__name__)

TEXT_WORDS = 16
MAX_TEXT_LENGTH = TEXT_WORDS * 2


@dataclass(frozen=True)
class TextWriteResult:
    ok: bool
    message: str


def validate_text(text: str) -> None:
    """書き込める文字列か確かめる。使えない文字や長すぎる場合は ValueError。"""
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"文字列は {MAX_TEXT_LENGTH} 文字以内で入力してください（{len(text)} 文字）"
        )
    invalid = sorted({c for c in text if not 0x20 <= ord(c) <= 0x7E})
    if invalid:
        shown = " ".join(repr(c) for c in invalid[:5])
        raise ValueError(f"半角英数字と記号のみ入力できます（使えない文字: {shown}）")


def encode_text(text: str) -> list[int]:
    """文字列を TEXT_WORDS 点のワード値に変換する。"""
    validate_text(text)
    data = text.encode("ascii").ljust(MAX_TEXT_LENGTH, b"\0")
    return [data[i] | (data[i + 1] << 8) for i in range(0, MAX_TEXT_LENGTH, 2)]


def decode_text(words: list[int]) -> str:
    """ワード値を文字列に戻す。最初の 0 で終わりとみなす。"""
    data = b"".join(word.to_bytes(2, "little") for word in words)
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace")


def write_text(client: PlcClient, head: Device, text: str) -> TextWriteResult:
    """文字列を head から TEXT_WORDS 点に書き込み、読み直して確かめる。"""
    last = head.offset(TEXT_WORDS - 1)
    try:
        values = encode_text(text)
    except ValueError as e:
        return TextWriteResult(False, str(e))
    try:
        if not client.is_connected:
            client.connect()
        client.write_words(head, values)
        written = client.read_words(head, TEXT_WORDS)
    except PlcError as e:
        client.close()
        logger.warning("文字列の書き込みに失敗: %s", e)
        return TextWriteResult(False, f"{head}〜{last} への書き込みに失敗しました: {e}")
    if written != values:
        logger.warning("文字列の読み直し結果が一致しません: %s", written)
        return TextWriteResult(
            False, f"{head}〜{last} に書き込みましたが、読み直した内容が一致しません"
        )
    logger.info("文字列を書き込みました: %s〜%s = %r", head, last, text)
    return TextWriteResult(True, f"{head}〜{last} に {text!r} を書き込みました")
