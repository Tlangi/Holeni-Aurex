from forexbot.risk import daily_loss_blocked, position_size
import pytest


def test_position_size_is_capped():
    assert position_size(10000, .25, .001, .00001, 1, .01, 100, .01, .20) == .20


def test_daily_loss_guard():
    assert daily_loss_blocked(9899, 10000, 1.0)
    assert not daily_loss_blocked(9950, 10000, 1.0)


def test_position_size_blocks_below_broker_minimum():
    with pytest.raises(ValueError, match="below the broker minimum"):
        position_size(100, .25, .01, .00001, 1, .01, 100, .01, .20)
