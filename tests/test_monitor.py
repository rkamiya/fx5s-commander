from fx5s_commander.commands import Command, CommandSender, Outcome
from fx5s_commander.config import DEFAULT_DEVICES, DEFAULT_LAMPS
from fx5s_commander.monitor import Lamp, read_lamps
from fx5s_commander.plc.mock import MockPlcClient, simulate_ladder


def test_read_lamps(clock):
    plc = MockPlcClient(clock=clock)
    plc.bits[DEFAULT_LAMPS[Lamp.RUNNING]] = True

    reading = read_lamps(plc, DEFAULT_LAMPS)

    assert reading.states == {Lamp.RUNNING: True, Lamp.STOPPED: False}
    assert reading.error is None
    assert plc.writes == []


def test_read_lamps_failure_is_reported(clock):
    plc = MockPlcClient(clock=clock)
    plc.fail_connect = True

    reading = read_lamps(plc, DEFAULT_LAMPS)

    assert reading.states is None
    assert reading.error


def test_simulated_ladder_switches_lamps_on_commands(clock):
    plc = MockPlcClient(clock=clock)
    simulate_ladder(plc, DEFAULT_DEVICES, DEFAULT_LAMPS)
    sender = CommandSender(
        plc,
        DEFAULT_DEVICES,
        ack_timeout_sec=1.0,
        poll_interval_sec=0.05,
        clock=clock,
        sleep=clock.sleep,
    )

    def lamps():
        return read_lamps(plc, DEFAULT_LAMPS).states

    assert lamps() == {Lamp.RUNNING: False, Lamp.STOPPED: True}
    assert sender.send(Command.ON).outcome is Outcome.ACCEPTED
    assert lamps() == {Lamp.RUNNING: True, Lamp.STOPPED: False}
    assert sender.send(Command.STOP).outcome is Outcome.ACCEPTED
    assert lamps() == {Lamp.RUNNING: False, Lamp.STOPPED: True}
