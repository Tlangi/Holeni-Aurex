from datetime import datetime, timezone

from app.ig_cost_authority import crosses_ig_funding_boundary, research_cost_policy


def test_london_funding_boundary_tracks_dst_and_excludes_crossing():
    assert crosses_ig_funding_boundary(
        datetime(2026, 9, 15, 20, 30, tzinfo=timezone.utc), 120)
    assert not crosses_ig_funding_boundary(
        datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc), 120)
    # 22:00 London is 22:00 UTC after UK daylight saving ends.
    assert crosses_ig_funding_boundary(
        datetime(2026, 12, 15, 21, 30, tzinfo=timezone.utc), 60)


def test_intraday_policy_has_zero_commission_and_no_fabricated_funding_rate():
    policy = research_cost_policy(slippage_bps_per_side=0.5)
    assert policy["commission_bps_round_trip"] == 0
    assert policy["financing_bps_per_day"] == 0
    assert policy["financing_rollover_hour_utc"] is None
