from scripts.run_prospective_accumulation_worker import CYCLE_INTERVAL_SECONDS


def test_accumulation_cycle_matches_m15_evidence_cadence() -> None:
    assert CYCLE_INTERVAL_SECONDS == 15 * 60
