from datetime import datetime, timezone

import pytest

from app.research_baselines import bounded_candles


class Cursor:
    def __init__(self):
        self.query = None
        self.parameters = None

    def execute(self, query, parameters):
        self.query, self.parameters = query, parameters

    def fetchall(self):
        return []


def test_holdout_is_enforced_in_sql_and_before_query():
    cursor = Cursor()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 2, 1, tzinfo=timezone.utc)
    holdout = datetime(2024, 3, 1, tzinfo=timezone.utc)
    bounded_candles(cursor, "market-id", "M15", start_utc=start, end_utc=end, holdout_start_utc=holdout)
    assert "open_time_utc < %s" in cursor.query
    assert cursor.parameters[-1] == holdout
    with pytest.raises(ValueError, match="holdout"):
        bounded_candles(cursor, "market-id", "M5", start_utc=start,
                        end_utc=holdout, holdout_start_utc=holdout)
    with pytest.raises(ValueError, match="Unsupported"):
        bounded_candles(cursor, "market-id", "H1", start_utc=start,
                        end_utc=end, holdout_start_utc=holdout)
