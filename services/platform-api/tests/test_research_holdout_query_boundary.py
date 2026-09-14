from datetime import datetime

from app.model_pipeline import _market_frame


class Cursor:
    def __init__(self):
        self.sql = ""
        self.parameters = ()

    def execute(self, sql, parameters):
        self.sql = sql
        self.parameters = parameters

    def fetchall(self):
        return []


def test_m15_query_excludes_holdout_in_sql_not_after_fetch():
    cursor = Cursor()
    start = datetime(2026, 8, 20)
    holdout_start = datetime(2026, 9, 10)
    _market_frame(cursor, "market-id", from_utc=start, before_utc=holdout_start)
    assert "open_time_utc >= %s" in cursor.sql
    assert "open_time_utc < %s" in cursor.sql
    assert cursor.parameters == ("market-id", start, holdout_start)
