from datetime import datetime, timezone
from app.historical_backfill import _next_month


def test_month_partition_handles_year_boundary() -> None:
    assert _next_month(datetime(2025,12,1,tzinfo=timezone.utc)) == datetime(2026,1,1,tzinfo=timezone.utc)
