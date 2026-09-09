from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.historical_backfill import (_next_month, download_partition, partition_priority,
                                     recent_month_boundaries)


def test_month_partition_handles_year_boundary() -> None:
    assert _next_month(datetime(2025,12,1,tzinfo=timezone.utc)) == datetime(2026,1,1,tzinfo=timezone.utc)


def test_recent_campaign_is_current_plus_two_calendar_months() -> None:
    start, end = recent_month_boundaries(datetime(2026, 9, 9, 6, 17, 44, tzinfo=timezone.utc), 3)
    assert start == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 9, 6, 17, tzinfo=timezone.utc)


def test_backfill_priority_is_governed_and_newest_first() -> None:
    end = datetime(2026, 9, 9, tzinfo=timezone.utc)
    assert partition_priority("USDJPY", datetime(2026, 9, 1), end) < partition_priority(
        "USDJPY", datetime(2026, 8, 1), end)
    assert partition_priority("USDJPY", datetime(2026, 7, 1), end) < partition_priority(
        "EURUSD", datetime(2026, 9, 1), end)


def test_partition_download_is_daily_resumable_and_assembles_once(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        directory = Path(command[command.index("-dir") + 1])
        filename = command[command.index("-fn") + 1]
        target = directory / f"{filename}.csv"
        target.write_text(
            "timestamp,askPrice,bidPrice\n1,150.02,150.00\n" if len(calls) == 1 else "",
            encoding="ascii",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.historical_backfill.subprocess.run", run)
    job = {"backfill_job_id": "job-1", "vendor_symbol": "USDJPY",
           "partition_start_utc": datetime(2026, 7, 1),
           "partition_end_utc": datetime(2026, 7, 3)}
    target = download_partition(tmp_path / "cli.cmd", tmp_path / "out", job)
    assert len(calls) == 2
    assert target.read_text(encoding="ascii").splitlines() == [
        "timestamp,askPrice,bidPrice", "1,150.02,150.00",
    ]
    download_partition(tmp_path / "cli.cmd", tmp_path / "out", job)
    assert len(calls) == 2
