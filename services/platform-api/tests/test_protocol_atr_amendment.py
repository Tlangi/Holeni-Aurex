import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_atr_amendment_matches_protocol_and_precedes_outcomes():
    protocol = json.loads((ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json").read_text())
    amendment = json.loads((ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1_ATR_AMENDMENT.json").read_text())
    digest = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert amendment["amends_protocol_sha256"] == digest
    assert amendment["outcome_access_before_amendment"] is False
    assert amendment["atr"]["periods"] == 14
    assert amendment["holdout_accessed"] is False
    assert amendment["model_training_performed"] is False


def test_cost_authority_is_spread_only_and_never_grants_order_authority():
    costs = json.loads((ROOT / "docs/research/AUREX_IG_ZA_COST_AUTHORITY_V1.json").read_text())
    assert costs["commission_bps_round_trip"] == 0
    assert costs["financing_rate"] == "VARIABLE_NOT_FROZEN"
    assert "EXCLUDE" in costs["financing_policy"]
    assert costs["broker_order_authority"] is False
    assert costs["deal_size_increment_authority"] is False
