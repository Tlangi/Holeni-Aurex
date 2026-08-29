from datetime import datetime, timezone

from forexbot.journal import Journal


def test_bar_state_and_daily_equity_persist(tmp_path):
    path = tmp_path / "journal.db"
    journal = Journal(str(path))
    bar = datetime(2026, 8, 16, tzinfo=timezone.utc)
    journal.mark_bar("EURUSD", bar)
    assert Journal(str(path)).bar_processed("EURUSD", bar)
    assert journal.daily_start_equity(10000) == 10000
    assert Journal(str(path)).daily_start_equity(9000) == 10000
