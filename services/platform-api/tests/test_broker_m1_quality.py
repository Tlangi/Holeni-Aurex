from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.broker_m1_quality import assess_m1_rows


def _rows():
    start = datetime(2026, 9, 15, 12, 0)
    return [{"open_time_utc": start + timedelta(minutes=i),
             "source": "IG_LIGHTSTREAMER", "completed": True,
             "quality_status": "PASS", "ingested_at_utc": start + timedelta(minutes=i),
             "bid_open": Decimal("1.1000"), "bid_high": Decimal("1.1004"),
             "bid_low": Decimal("1.0998"), "bid_close": Decimal("1.1002"),
             "ask_open": Decimal("1.1002"), "ask_high": Decimal("1.1006"),
             "ask_low": Decimal("1.1000"), "ask_close": Decimal("1.1004")}
            for i in range(3)]


def _assess(rows, view="CURRENT_IG_EXECUTION"):
    return assess_m1_rows(rows, view=view, expected_session=lambda _: True,
                          now_utc=datetime(2026, 9, 15, 12, 3,
                                           tzinfo=timezone.utc))


def test_complete_ig_path_passes_without_research_rows():
    assert _assess(_rows())["status"] == "PASS"


def test_repaired_research_row_never_fills_ig_execution_gap():
    rows = _rows()
    rows[1]["source"] = "DUKASCOPY_M1_REPAIR"
    assert _assess(rows)["missing_expected_session_m1"] == 1
    assert _assess(rows)["status"] == "BLOCKED"
    assert _assess(rows, "HYBRID_RESEARCH")["missing_expected_session_m1"] == 0


def test_source_duplicates_and_invalid_quotes_are_reported():
    rows = _rows()
    rows.append(dict(rows[0]))
    rows[1]["ask_close"] = Decimal("1.1001")
    result = _assess(rows)
    assert result["duplicates_in_source_rows"] == 1
    assert result["crossed_open_or_close"] == 1
    assert result["status"] == "BLOCKED"


def test_session_break_is_not_a_gap():
    rows = _rows()
    rows.pop(1)
    result = assess_m1_rows(rows, view="RAW_IG",
        expected_session=lambda at: at.minute != 1,
        now_utc=datetime(2026, 9, 15, 12, 3, tzinfo=timezone.utc))
    assert result["missing_expected_session_m1"] == 0
