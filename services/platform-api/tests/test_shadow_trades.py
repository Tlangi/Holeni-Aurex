from decimal import Decimal

from app.shadow_trades import resolve_shadow_candle, shadow_pnl


def test_shadow_buy_closes_at_target_and_calculates_cost_aware_pnl() -> None:
    result = resolve_shadow_candle("BUY", stop=Decimal("1.09"), target=Decimal("1.12"),
                                   high=Decimal("1.121"), low=Decimal("1.10"), close=Decimal("1.115"))
    assert result.closed and result.reason == "TAKE_PROFIT" and result.price == Decimal("1.12")
    assert shadow_pnl("BUY", entry=Decimal("1.10"), current=result.price, size=Decimal("2"),
                      value_per_price_point_zar=Decimal("1000"), estimated_cost_zar=Decimal("1")) == Decimal("39")


def test_shadow_uses_conservative_stop_when_both_levels_hit() -> None:
    result = resolve_shadow_candle("BUY", stop=Decimal("1.09"), target=Decimal("1.12"),
                                   high=Decimal("1.13"), low=Decimal("1.08"), close=Decimal("1.11"))
    assert result.reason == "STOP_LOSS" and result.price == Decimal("1.09")


def test_shadow_sell_marks_unrealized_without_closing() -> None:
    result = resolve_shadow_candle("SELL", stop=Decimal("1.12"), target=Decimal("1.08"),
                                   high=Decimal("1.11"), low=Decimal("1.09"), close=Decimal("1.095"))
    assert not result.closed and result.price == Decimal("1.095")
