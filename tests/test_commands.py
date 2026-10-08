import pytest

from fx5s_commander.commands import Command, CommandSender, Outcome
from fx5s_commander.config import DEFAULT_DEVICES
from fx5s_commander.devices import Device
from fx5s_commander.plc.client import DeviceNotAllowedError, GuardedPlcClient
from fx5s_commander.plc.mock import MockPlcClient

M100 = Device("M", 100)


@pytest.fixture
def plc(clock):
    return MockPlcClient(ack_delay_sec=0.2, clock=clock)


@pytest.fixture
def sender(plc, clock):
    return CommandSender(
        GuardedPlcClient(plc, DEFAULT_DEVICES.values()),
        DEFAULT_DEVICES,
        ack_timeout_sec=1.0,
        poll_interval_sec=0.05,
        clock=clock,
        sleep=clock.sleep,
    )


def test_accepted_when_plc_resets_device(sender, plc):
    result = sender.send(Command.ON)

    assert result.outcome is Outcome.ACCEPTED
    assert result.device == M100
    assert plc.writes == [(M100, True)]
    assert plc.bits[M100] is False
    assert 0.2 <= result.elapsed_sec < 1.0


def test_same_command_can_be_sent_repeatedly(sender):
    for _ in range(3):
        assert sender.send(Command.ON).outcome is Outcome.ACCEPTED


def test_cancelled_when_plc_does_not_respond(sender, plc):
    plc.ack_delay_sec = None

    result = sender.send(Command.ON)

    assert result.outcome is Outcome.NOT_ACCEPTED
    assert plc.writes == [(M100, True), (M100, False)]
    assert plc.bits[M100] is False
    assert result.elapsed_sec >= 1.0


def test_busy_when_previous_command_still_pending(sender, plc):
    plc.connect()
    plc.bits[M100] = True

    result = sender.send(Command.ON)

    assert result.outcome is Outcome.BUSY
    assert plc.writes == []


def test_connect_failure_is_reported_not_raised(sender, plc):
    plc.fail_connect = True

    result = sender.send(Command.STOP)

    assert result.outcome is Outcome.ERROR
    assert plc.writes == []


def test_reconnects_after_error(sender, plc):
    plc.fail_connect = True
    assert sender.send(Command.ON).outcome is Outcome.ERROR

    plc.fail_connect = False
    assert sender.send(Command.ON).outcome is Outcome.ACCEPTED


def test_error_during_handshake_warns_command_may_have_run(sender, plc, clock):
    original_sleep = clock.sleep

    def fail_after_write(seconds):
        plc.fail_io = True
        original_sleep(seconds)

    sender._sleep = fail_after_write

    result = sender.send(Command.ON)

    assert result.outcome is Outcome.ERROR
    assert "実行された可能性" in result.message
    assert not plc.is_connected


def test_check_connection_reads_without_writing(sender, plc):
    result = sender.check_connection()

    assert result.ok
    assert "M100=OFF" in result.message
    assert plc.writes == []


def test_check_connection_failure(sender, plc):
    plc.fail_connect = True
    assert not sender.check_connection().ok


def test_guard_rejects_unlisted_device(plc):
    guarded = GuardedPlcClient(plc, [M100])
    guarded.connect()
    guarded.write_bit(M100, True)

    with pytest.raises(DeviceNotAllowedError):
        guarded.write_bit(Device("M", 0), True)
    assert plc.writes == [(M100, True)]
