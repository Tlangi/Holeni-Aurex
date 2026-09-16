"""Join prospective feature, ATR, execution-path and funding evidence."""
from __future__ import annotations

from hashlib import sha256
import json


JOIN_VERSION = "PROSPECTIVE_EXECUTABLE_OPPORTUNITY_JOIN_V1"


def join_opportunity(*, market: str, decision_at_utc: str, m15_candle_id: int,
                     atr: dict[str, object], feature: dict[str, object],
                     path: dict[str, object], crosses_rollover: bool) -> dict[str, object]:
    identity_payload = {"version": JOIN_VERSION, "market": market,
        "decision_at_utc": decision_at_utc, "m15_candle_id": m15_candle_id}
    opportunity_id = sha256(json.dumps(identity_payload, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    gates = {"atr_ready": atr.get("status") == "COMPLETE",
        "feature_ready": feature.get("status") == "COMPLETE",
        "no_rollover": not crosses_rollover,
        "ig_m1_path_ready": path.get("status") == "COMPLETE_IG_M1_PATH"}
    if not gates["atr_ready"]:
        reason = f"ATR:{atr.get('reason') or 'UNVERIFIABLE'}"
    elif not gates["feature_ready"]:
        reason = f"FEATURE:{feature.get('reason') or 'UNVERIFIABLE'}"
    elif not gates["no_rollover"]:
        reason = "FUNDING_BOUNDARY_IN_MAX_HORIZON"
    elif not gates["ig_m1_path_ready"]:
        reason = f"IG_PATH:{path.get('reason') or 'UNVERIFIABLE'}"
    else:
        reason = "JOINED_TRAINING_INPUT_READY"
    return {**identity_payload, "opportunity_id": opportunity_id,
        "gates": gates, "status": "JOINED" if all(gates.values()) else "ACCUMULATING",
        "reason": reason, "atr_snapshot_sha256": atr.get("snapshot_sha256"),
        "feature_snapshot_sha256": feature.get("snapshot_sha256"),
        "ig_m1_path_sha256": path.get("source_ig_m1_path_sha256"),
        "ig_m1_complete_minutes": path.get("complete_m1_minutes", 0),
        "ig_m1_first_missing_utc": path.get("first_missing_m1_utc")}
