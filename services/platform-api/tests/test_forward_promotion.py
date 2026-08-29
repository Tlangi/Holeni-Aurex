from decimal import Decimal

import pytest

from app.config import Settings
from app.demo_execution import OneOffDemoExecutionRequest, execute_one_off_demo
from app.forward_promotion import maximum_consecutive_losses, maximum_drawdown_pct
from app.ig_execution import IGExecutionBlocked


def test_forward_drawdown_uses_cost_aware_realized_pnl_sequence() -> None:
    pnl = [Decimal("100"), Decimal("-40"), Decimal("-80"), Decimal("50")]
    assert maximum_drawdown_pct(pnl, Decimal("1000")) == Decimal("12.00")


def test_forward_promotion_counts_consecutive_losses() -> None:
    pnl = [Decimal("-1"), Decimal("-2"), Decimal("3"), Decimal("-4")]
    assert maximum_consecutive_losses(pnl) == 2


def test_one_off_execution_fails_before_database_access_when_opt_in_is_disabled() -> None:
    settings = Settings(
        _env_file=None, trading_mode="disabled", allow_demo_trading=False,
        allow_live_trading=False, ig_environment="demo", broker_environment="demo",
    )
    request = OneOffDemoExecutionRequest(
        order_intent_id="00000000-0000-0000-0000-000000000000",
        acknowledgement="EXECUTE_ONE_OFF_IG_DEMO",
    )
    with pytest.raises(IGExecutionBlocked, match="opt-in remains disabled"):
        execute_one_off_demo(settings, "tenant", "user", request)


def test_one_off_execution_requires_exact_acknowledgement() -> None:
    with pytest.raises(ValueError):
        OneOffDemoExecutionRequest(
            order_intent_id="00000000-0000-0000-0000-000000000000",
            acknowledgement="YES",
        )
