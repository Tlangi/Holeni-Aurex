from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.market_data import _completed_historical_bucket, _timestamp


def test_timestamp_accepts_ig_slash_format_as_utc() -> None:
    assert _timestamp("2026/08/31 22:00:00") == datetime(2026, 8, 31, 22, 0, tzinfo=timezone.utc)


def test_timestamp_normalizes_iso_offset_to_utc() -> None:
    assert _timestamp("2026-09-01T00:00:00+02:00") == datetime(2026, 8, 31, 22, 0, tzinfo=timezone.utc)


def test_timestamp_rejects_unrecognized_values() -> None:
    with pytest.raises(ValueError, match="Unsupported historical candle timestamp"):
        _timestamp("31 August 2026")


def test_historical_bucket_must_be_closed_at_server_time() -> None:
    now = datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc)
    assert _completed_historical_bucket(datetime(2026, 9, 1, 6, 45, tzinfo=timezone.utc), 15, now=now)
    assert not _completed_historical_bucket(datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc), 15, now=now)
    assert not _completed_historical_bucket(datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc), 15, now=now)
