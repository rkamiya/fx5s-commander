import pytest

from fx5s_commander.devices import M_DEVICE_MAX, Device, parse_device


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
