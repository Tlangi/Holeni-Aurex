from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.historical_market_data import (
    InstrumentEquivalence, PriceCompleteness, aggregate_ticks_to_m1,
    parse_histdata_m1, parse_histdata_tick, research_eligible,
)


def test_histdata_m1_is_fixed_est_to_utc_and_never_fabricates_ask() -> None:
    row = parse_histdata_m1("20260115 120000;1.1;1.2;1.0;1.15;3")
    assert row.timestamp_utc == datetime(2026,1,15,17,0,tzinfo=timezone.utc)
    assert row.completeness is PriceCompleteness.BID_ONLY
    assert row.ask_open is None and row.ask_close is None


def test_histdata_fixed_est_does_not_apply_summer_dst() -> None:
    row = parse_histdata_m1("20260715 120000;1.1;1.2;1.0;1.15;0")
    assert row.timestamp_utc.hour == 17


def test_tick_bid_ask_aggregates_each_side_independently() -> None:
    rows = [parse_histdata_tick("20260115 120001000,1.10,1.12,0"),
            parse_histdata_tick("20260115 120059000,1.08,1.13,0")]
    candle = aggregate_ticks_to_m1(rows)[0]
    assert candle.bid_open == Decimal("1.10") and candle.bid_low == Decimal("1.08")
    assert candle.ask_open == Decimal("1.12") and candle.ask_high == Decimal("1.13")
    assert candle.completeness is PriceCompleteness.BID_ASK_FULL


def test_crossed_tick_is_rejected() -> None:
    with pytest.raises(ValueError, match="bid/ask"):
        parse_histdata_tick("20260115 120001000,1.12,1.10,0")


def test_germany_index_reference_cannot_be_research_eligible() -> None:
    assert not research_eligible(quality_state="VALIDATED",
                                 equivalence=InstrumentEquivalence.INDEX_REFERENCE,
                                 point_in_time_verified=True)
