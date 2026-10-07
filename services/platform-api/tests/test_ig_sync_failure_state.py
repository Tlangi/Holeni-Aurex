from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.ig_sync import sync_failure_requires_degradation, transient_failure_grace_seconds


def test_single_transient_failure_preserves_recent_current_component() -> None:
    observed = datetime(2026, 10, 7, 17, 42, tzinfo=timezone.utc)
    assert not sync_failure_requires_degradation(
        category="BROKER_UNAVAILABLE",
        last_checked_at=observed - timedelta(minutes=5),
        observed_at=observed,
        grace_seconds=15 * 60,
    )


def test_persistent_or_authentication_failure_degrades_component() -> None:
    observed = datetime(2026, 10, 7, 17, 42, tzinfo=timezone.utc)
    assert sync_failure_requires_degradation(
        category="BROKER_UNAVAILABLE",
        last_checked_at=observed - timedelta(minutes=16),
        observed_at=observed,
        grace_seconds=15 * 60,
    )
    assert sync_failure_requires_degradation(
        category="AUTHENTICATION",
        last_checked_at=observed - timedelta(seconds=1),
        observed_at=observed,
        grace_seconds=15 * 60,
    )


def test_transient_grace_covers_three_normal_sync_intervals() -> None:
    settings = Settings(account_sync_seconds=300, stale_after_seconds=180)
    assert transient_failure_grace_seconds(settings) == 900
