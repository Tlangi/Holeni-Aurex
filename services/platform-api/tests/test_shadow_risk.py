from dataclasses import replace
from decimal import Decimal

from app.shadow_engine import RiskInput, evaluate_risk


def valid_input() -> RiskInput:
    return RiskInput(
        direction="BUY", confidence=Decimal("0.70"), model_validated=True,
        market_data_fresh=True, reconciliation_clear=True, equity_zar=Decimal("100000"),
        start_day_equity_zar=Decimal("100000"), risk_per_trade_pct=Decimal("0.25"),
        daily_loss_limit_pct=Decimal("1"), open_positions=0, market_positions=0,
        max_open_positions=2, max_positions_per_market=1, current_price=Decimal("1.10000"),
        atr=Decimal("0.001"), min_deal_size=Decimal("1"), size_increment=Decimal("1"),
        min_stop_distance=Decimal("0.0005"), value_per_price_point_zar=Decimal("100"),
        available_margin_zar=Decimal("1000000"), margin_factor_pct=Decimal("5"),
    )


def test_risk_approves_only_with_sized_stop_and_take_profit() -> None:
    result = evaluate_risk(valid_input())
    assert result.approved
    assert result.size and result.size >= Decimal("1")
    assert result.stop and result.stop < Decimal("1.10000")
    assert result.take_profit and result.take_profit > Decimal("1.10000")


def test_unvalidated_model_is_rejected_before_sizing() -> None:
    result = evaluate_risk(replace(valid_input(), model_validated=False))
    assert not result.approved
    assert result.reason == "MODEL_NOT_VALIDATED"


def test_daily_loss_and_reconciliation_are_hard_blocks() -> None:
    loss = evaluate_risk(replace(valid_input(), equity_zar=Decimal("98900")))
    reconciliation = evaluate_risk(replace(valid_input(), reconciliation_clear=False))
    assert loss.reason == "DAILY_LOSS_LIMIT"
    assert reconciliation.reason == "UNRESOLVED_RECONCILIATION"


def test_missing_broker_value_never_uses_a_guess() -> None:
    result = evaluate_risk(replace(valid_input(), value_per_price_point_zar=None))
    assert not result.approved
    assert result.reason == "MISSING_BROKER_MARKET_RULES"


def test_missing_profit_objective_never_changes_trading_risk() -> None:
    low_objective = evaluate_risk(replace(valid_input(), preferred_daily_return_pct=Decimal("1")))
    high_objective = evaluate_risk(replace(valid_input(), preferred_daily_return_pct=Decimal("10")))
    assert low_objective.planned_risk_zar == high_objective.planned_risk_zar


def test_losses_can_only_reduce_or_block_new_trade_risk() -> None:
    normal = evaluate_risk(valid_input())
    after_two = evaluate_risk(replace(valid_input(), consecutive_losses=2))
    after_three = evaluate_risk(replace(valid_input(), consecutive_losses=3))
    after_four = evaluate_risk(replace(valid_input(), consecutive_losses=4))
    assert normal.planned_risk_zar >= after_two.planned_risk_zar >= after_three.planned_risk_zar
    assert not after_four.approved
    assert after_four.reason == "CONSECUTIVE_LOSS_LIMIT"


def test_profit_protection_reduces_risk_and_daily_lock_blocks_entries() -> None:
    normal = evaluate_risk(valid_input())
    protected = evaluate_risk(replace(valid_input(), profit_protection_state="PROFIT_PROTECTION"))
    locked = evaluate_risk(replace(valid_input(), profit_protection_state="DAILY_TARGET_LOCKED"))
    assert protected.planned_risk_zar < normal.planned_risk_zar
    assert locked.reason == "DAILY_PROFIT_LOCK"


def test_non_current_ledger_portfolio_limit_trade_limit_and_margin_fail_closed() -> None:
    assert evaluate_risk(replace(valid_input(), ledger_status="BLOCKED")).reason == "DAILY_RISK_LEDGER_BLOCKED"
    assert evaluate_risk(replace(valid_input(), reserved_risk_zar=Decimal("700"))).reason == "MAX_PORTFOLIO_RISK"
    assert evaluate_risk(replace(valid_input(), trades_today=6)).reason == "MAX_TRADES_PER_DAY"
    assert evaluate_risk(replace(valid_input(), margin_factor_pct=None)).reason == "MARGIN_EVIDENCE_MISSING"
    assert evaluate_risk(replace(valid_input(), available_margin_zar=Decimal("1"))).reason == "INSUFFICIENT_AVAILABLE_MARGIN"


def test_configured_reward_risk_ratio_drives_target() -> None:
    item = replace(valid_input(), min_reward_risk_ratio=Decimal("1.5"))
    result = evaluate_risk(item)
    assert result.approved and result.stop and result.take_profit
    assert (result.take_profit - item.current_price) == (
        item.current_price - result.stop
    ) * Decimal("1.5")
