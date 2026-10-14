import pytest

from fx5s_commander.devices import (
    D_DEVICE_MAX,
    M_DEVICE_MAX,
    Device,
    parse_device,
    parse_word_device,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("M100", Device("M", 100)), ("m0", Device("M", 0)), (" M101 ", Device("M", 101))],
)
def test_parse_valid(text, expected):
    assert parse_device(text) == expected


@pytest.mark.parametrize("text", ["X0", "Y0", "D100", "SM400", "M", "100", "M-1", "M1.0", ""])
def test_parse_rejects_non_m_or_malformed(text):
    with pytest.raises(ValueError):
        parse_device(text)


def test_parse_rejects_out_of_range():
    assert parse_device(f"M{M_DEVICE_MAX}") == Device("M", M_DEVICE_MAX)
    with pytest.raises(ValueError):
        parse_device(f"M{M_DEVICE_MAX + 1}")


def test_str():
    assert str(Device("M", 100)) == "M100"


def test_parse_word_device():
    assert parse_word_device("d100") == Device("D", 100)
    assert parse_word_device(f"D{D_DEVICE_MAX - 15}", words=16) == Device("D", D_DEVICE_MAX - 15)


@pytest.mark.parametrize("text", ["M100", "R100", "D", f"D{D_DEVICE_MAX + 1}"])
def test_parse_word_device_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_word_device(text)


def test_parse_word_device_rejects_range_overflow():
    with pytest.raises(ValueError, match="超えます"):
        parse_word_device(f"D{D_DEVICE_MAX - 14}", words=16)


def test_offset():
    assert Device("D", 100).offset(15) == Device("D", 115)
