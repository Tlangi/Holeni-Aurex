from decimal import Decimal

from app.m1_m5_reconciliation import instrument_tolerance, quality_class


def test_tolerance_uses_instrument_tick_scale() -> None:
    assert instrument_tolerance(reference_price=Decimal("150"), tick_size=Decimal("0.001"),
                                spread=None, atr=None,
                                relative_ratio=Decimal("0.000001")) == Decimal("0.002")


def test_reconciliation_quality_classes_are_not_exact_equality() -> None:
    assert quality_class(comparable=1000, within=1000,
                         minimum_match=Decimal("0.999")) == "MATCH_STRONG"
    assert quality_class(comparable=1000, within=995,
                         minimum_match=Decimal("0.999")) == "MATCH_ACCEPTABLE"
    assert quality_class(comparable=1000, within=980,
                         minimum_match=Decimal("0.999")) == "MISMATCH_REVIEW"
    assert quality_class(comparable=0, within=0,
                         minimum_match=Decimal("0.999")) == "NO_BASELINE"
