from datetime import datetime, timezone

from app.health_monitor import dual_time


def test_dual_time_labels_utc_and_south_african_time() -> None:
    assert dual_time(datetime(2026,9,8,4,50)) == (
        "2026-09-08 04:50:00 UTC / 2026-09-08 06:50:00 SAST"
    )
    assert dual_time(datetime(2026,9,8,4,50,tzinfo=timezone.utc)).endswith(
        "2026-09-08 06:50:00 SAST"
    )
