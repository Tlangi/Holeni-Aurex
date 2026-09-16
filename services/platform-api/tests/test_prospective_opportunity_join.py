from app.prospective_opportunity_join import join_opportunity


def _item(atr="COMPLETE", feature="COMPLETE", path="COMPLETE_IG_M1_PATH", rollover=False):
    return join_opportunity(market="EURUSD", decision_at_utc="2026-09-16T12:15:02+00:00",
        m15_candle_id=1,
        atr={"status": atr, "reason": "ATR_GAP", "snapshot_sha256": "a" * 64},
        feature={"status": feature, "reason": "FEATURE_GAP", "snapshot_sha256": "b" * 64},
        path={"status": path, "reason": "IG_M1_MISSING",
              "source_ig_m1_path_sha256": "c" * 64, "complete_m1_minutes": 120,
              "first_missing_m1_utc": None}, crosses_rollover=rollover)


def test_complete_evidence_produces_stable_joined_identity():
    first = _item()
    assert first == _item()
    assert first["status"] == "JOINED"
    assert len(first["opportunity_id"]) == 64


def test_gate_order_keeps_warmup_and_features_distinct_from_path():
    assert _item(atr="UNVERIFIABLE", feature="UNVERIFIABLE", path="UNVERIFIABLE")["reason"] == "ATR:ATR_GAP"
    assert _item(feature="UNVERIFIABLE", path="UNVERIFIABLE")["reason"] == "FEATURE:FEATURE_GAP"
    assert _item(rollover=True, path="UNVERIFIABLE")["reason"] == "FUNDING_BOUNDARY_IN_MAX_HORIZON"
    assert _item(path="UNVERIFIABLE")["reason"] == "IG_PATH:IG_M1_MISSING"
