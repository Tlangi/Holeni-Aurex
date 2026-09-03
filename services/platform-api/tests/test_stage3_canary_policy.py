from dataclasses import replace
from decimal import Decimal

from app.stage3_canary_policy import Stage3CanaryInput, stage3_canary_rejection


def eligible() -> Stage3CanaryInput:
    return Stage3CanaryInput("USDJPY", "USDJPY", Decimal("0.5"), Decimal("0.5"),
                             True, True, 0, 0, False)


def test_boring_first_demo_order_contract() -> None:
    assert stage3_canary_rejection(eligible()) is None
    assert stage3_canary_rejection(replace(eligible(), attempt_market="EURUSD"))
    assert stage3_canary_rejection(replace(eligible(), requested_size=Decimal("1")))
    assert stage3_canary_rejection(replace(eligible(), stop_present=False))
    assert stage3_canary_rejection(replace(eligible(), open_position_count=1))
    assert stage3_canary_rejection(replace(eligible(), unresolved_submission=True))
