from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.dukascopy_import import Candle, _rejection_code, aggregate_bucket, identify_file, parse_candle


def market() -> dict[str, object]:
    return {
        "calendar_code": "FX_24X5", "market_timezone": "UTC",
        "session_open_local": None, "session_close_local": None,
    }


def test_dukascopy_filename_maps_germany_40() -> None:
    assert identify_file(Path("deuidxeur-m5-bid-2024-01-01-2026-08-26.csv")) == ("GERMANY40", "BID")


def test_unsupported_or_ask_file_is_rejected() -> None:
    with pytest.raises(ValueError):
        identify_file(Path("eurusd-m5-ask-2024.csv"))


def test_parse_requires_valid_aligned_ohlc() -> None:
    candle = parse_candle(
        {"timestamp": "1704067200000", "open": "1.10", "high": "1.11",
         "low": "1.09", "close": "1.105"}, market(), set(),
    )
    assert candle.opened == datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="OHLC"):
        parse_candle(
            {"timestamp": "1704067200000", "open": "1.10", "high": "1.09",
             "low": "1.08", "close": "1.105"}, market(), set(),
        )


def test_quarantine_rejection_codes_are_stable() -> None:
    assert _rejection_code("Invalid OHLC envelope") == "INVALID_OHLC"
    assert _rejection_code("Prices must be finite and positive") == "NON_POSITIVE_OR_NON_FINITE"
    assert _rejection_code("Timestamp is not aligned") == "INVALID_TIMESTAMP"


def test_only_complete_three_candle_buckets_aggregate() -> None:
    opened = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    rows = [
        Candle(opened, Decimal("1"), Decimal("2"), Decimal("0.5"), Decimal("1.5"), True),
        Candle(opened.replace(minute=5), Decimal("1.5"), Decimal("2.2"), Decimal("1.2"), Decimal("2"), True),
        Candle(opened.replace(minute=10), Decimal("2"), Decimal("2.1"), Decimal("1.7"), Decimal("1.8"), True),
    ]
    result = aggregate_bucket(opened, rows)
    assert result and result.open == Decimal("1") and result.close == Decimal("1.8")
    assert aggregate_bucket(opened, rows[:2]) is None
