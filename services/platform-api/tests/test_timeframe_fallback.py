from datetime import datetime, timedelta
from decimal import Decimal

from app.timeframe_fallback import (DERIVED_FROM_M1, M1_MISSING_M5_FALLBACK_AVAILABLE,
                                    derive_m5_from_complete_m1, feature_availability,
                                    mark_m1_gap_fallback)


def _row(stamp: datetime, value: str) -> dict[str, object]:
    price = Decimal(value)
    return {"timestamp_utc": stamp, "bid_open": price, "bid_high": price + Decimal("0.2"),
            "bid_low": price - Decimal("0.1"), "bid_close": price + Decimal("0.1"),
            "ask_open": price + Decimal("0.02"), "ask_high": price + Decimal("0.22"),
            "ask_low": price - Decimal("0.08"), "ask_close": price + Decimal("0.12"),
            "is_derived": False}


def test_one_m5_never_creates_five_fake_m1_candles() -> None:
    bucket = datetime(2026, 9, 9, 8, 0)
    missing = [bucket + timedelta(minutes=index) for index in range(5)]
    evidence = mark_m1_gap_fallback(missing, [bucket])
    assert len(evidence) == 5
    assert set(evidence.values()) == {M1_MISSING_M5_FALLBACK_AVAILABLE}
    assert list(evidence) == missing  # metadata keys only; no candle values exist


def test_five_genuine_m1_candles_safely_derive_m5() -> None:
    bucket = datetime(2026, 9, 9, 8, 0)
    result = derive_m5_from_complete_m1(
        [_row(bucket + timedelta(minutes=index), str(150 + index)) for index in range(5)])
    assert result is not None
    assert result.source == DERIVED_FROM_M1
    assert result.bid_open == Decimal("150")
    assert result.bid_high == Decimal("154.2")
    assert result.bid_low == Decimal("149.9")
    assert result.bid_close == Decimal("154.1")


def test_incomplete_or_derived_m1_cannot_derive_m5() -> None:
    bucket = datetime(2026, 9, 9, 8, 0)
    assert derive_m5_from_complete_m1([_row(bucket + timedelta(minutes=index), "150")
                                       for index in range(4)]) is None
    rows = [_row(bucket + timedelta(minutes=index), "150") for index in range(5)]
    rows[2]["is_derived"] = True
    assert derive_m5_from_complete_m1(rows) is None


def test_feature_fallback_is_requirement_aware() -> None:
    assert feature_availability(requires_genuine_m1=True, m1_available=False,
                                m5_available=True) == "MISSING"
    assert feature_availability(requires_genuine_m1=False, m1_available=False,
                                m5_available=True) == M1_MISSING_M5_FALLBACK_AVAILABLE
