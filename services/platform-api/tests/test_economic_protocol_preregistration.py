from datetime import datetime
import json
from pathlib import Path

from app.executable_trade_outcome import ENTRY_POLICY_VERSION, LABEL_VERSION
from app.point_in_time_features import FEATURE_VERSION


PROTOCOL = Path(__file__).resolve().parents[3] / \
    "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json"


def test_protocol_freezes_nonpromotable_market_universe_before_validation():
    policy = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert policy["authority"] == "PRE_REGISTERED_NONPROMOTABLE_RESEARCH"
    assert policy["cohort_gate"]["model_promotion"] == "NONE"
    assert len(policy["markets"]) == 9
    assert policy["decision_universe"]["entry_policy_version"] == ENTRY_POLICY_VERSION
    assert policy["decision_universe"]["feature_version"] == FEATURE_VERSION
    assert policy["label_version"] == LABEL_VERSION
    assert policy["decision_universe"]["execution_source"].startswith("completed PASS IG_LIGHTSTREAMER")
    assert len(policy["policy_families"]) == 3
    chronology = policy["chronology"]
    assert datetime.fromisoformat(chronology["development_start_utc"].replace("Z", "+00:00")) < \
        datetime.fromisoformat(chronology["validation_start_utc"].replace("Z", "+00:00")) < \
        datetime.fromisoformat(chronology["untouched_holdout_start_utc"].replace("Z", "+00:00"))
    assert chronology["purge_before_each_boundary_minutes"] >= max(
        item["max_holding_minutes"] for item in policy["policy_families"])
    assert "unknown yields UNVERIFIABLE" in policy["cost_policy"]["commission"]
    assert policy["cost_policy"]["spread"].startswith("executable bid/ask")
