import pytest

from fx5s_commander.devices import Device
from fx5s_commander.plc.client import DeviceNotAllowedError, GuardedPlcClient
from fx5s_commander.plc.mock import MockPlcClient
from fx5s_commander.plc.slmp import SlmpPlcClient
from fx5s_commander.text import (
    MAX_TEXT_LENGTH,
    TEXT_WORDS,
    decode_text,
    encode_text,
    write_text,
)

D100 = Device("D", 100)
TEXT_DEVICES = [D100.offset(i) for i in range(TEXT_WORDS)]


def test_encode_sos_example():
    # 依頼時のサンプル: SOS → D100 = H4F53, D101 = H53
    words = encode_text("SOS")
    assert words[0] == 0x4F53
    assert words[1] == 0x0053
    assert words[2:] == [0] * (TEXT_WORDS - 2)
    assert len(words) == TEXT_WORDS


def test_encode_full_length():
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    assert len(text) == MAX_TEXT_LENGTH
    words = encode_text(text)
    assert words[0] == 0x4241  # "AB"
    assert words[-1] == 0x3534  # "45"
    assert decode_text(words) == text


def test_encode_empty_clears_all_words():
    assert encode_text("") == [0] * TEXT_WORDS


@pytest.mark.parametrize("text", ["A" * (MAX_TEXT_LENGTH + 1), "あいう", "tab\there", "é"])
def test_encode_rejects_invalid(text):
    with pytest.raises(ValueError):
        encode_text(text)


def test_decode_round_trip_with_symbols():
    text = "Hello, PLC! #1 ~"
    assert decode_text(encode_text(text)) == text


def make_plc(clock=None):
    plc = MockPlcClient()
    return plc, GuardedPlcClient(plc, [], TEXT_DEVICES)


def test_write_text_writes_all_words_and_verifies():
    plc, client = make_plc()

    result = write_text(client, D100, "SOS")

    assert result.ok
    assert "D100〜D115" in result.message
    assert plc.word_writes == [(D100, encode_text("SOS"))]
    assert plc.words[Device("D", 100)] == 0x4F53
    assert plc.words[Device("D", 101)] == 0x0053
    assert plc.words[Device("D", 115)] == 0


def test_write_text_overwrites_previous_longer_text():
    plc, client = make_plc()
    write_text(client, D100, "LONG MESSAGE TEXT")

    write_text(client, D100, "OK")

    assert decode_text([plc.words[d] for d in TEXT_DEVICES]) == "OK"


def test_write_text_reports_connection_error():
    plc, client = make_plc()
    plc.fail_connect = True

    result = write_text(client, D100, "SOS")

    assert not result.ok
    assert plc.word_writes == []


def test_write_text_detects_read_back_mismatch():
    plc, client = make_plc()
    original_read = plc.read_words
    plc.read_words = lambda head, count: [0] + original_read(head, count)[1:]

    result = write_text(client, D100, "SOS")

    assert not result.ok
    assert "一致しません" in result.message


def test_write_text_rejects_invalid_text_without_writing():
    plc, client = make_plc()

    result = write_text(client, D100, "あ")

    assert not result.ok
    assert plc.word_writes == []


def test_guard_rejects_words_outside_text_area():
    plc, client = make_plc()
    client.connect()

    with pytest.raises(DeviceNotAllowedError):
        client.write_words(Device("D", 101), [0] * TEXT_WORDS)  # D116 は許可外
    with pytest.raises(DeviceNotAllowedError):
        client.write_bit(Device("M", 100), True)
    assert plc.word_writes == []


class FakePymc:
    def __init__(self):
        self.written = None

    def batchwrite_wordunits(self, headdevice, values):
        self.written = (headdevice, values)

    def batchread_wordunits(self, headdevice, readsize):
        return [-1, 0x4F53][:readsize]


def test_slmp_converts_between_signed_and_unsigned_words():
    client = SlmpPlcClient("127.0.0.1", 5000, plc_type="L", timeout_sec=1)
    fake = FakePymc()
    client._plc = fake

    client.write_words(D100, [0xFFFF, 0x4F53])

    assert fake.written == ("D100", [-1, 0x4F53])
    assert client.read_words(D100, 2) == [0xFFFF, 0x4F53]
