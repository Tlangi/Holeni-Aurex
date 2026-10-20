"""Freeze V4 development membership after its preregistered horizon closes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.prospective_accumulation import evidence_sha256
from app.research_cohort_eligibility import canonical_sha256
from scripts.verify_prospective_v4_protocol import verify


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V4.json"
OUTPUT_PATH = ROOT / "docs/audits/AUREX_FROZEN_PROSPECTIVE_V4_DEVELOPMENT_COHORT.json"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def require_ready(protocol: dict[str, object], *, now: datetime | None = None) -> None:
    verify(protocol)
    clock = now or datetime.now(timezone.utc)
    if clock < utc(str(protocol["development_outcome_horizon_complete_utc"])):
        raise RuntimeError("V4_DEVELOPMENT_WINDOW_NOT_COMPLETE")


def freeze() -> dict[str, object]:
    if OUTPUT_PATH.exists():
        raise FileExistsError(f"Immutable V4 cohort already exists: {OUTPUT_PATH}")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    require_ready(protocol)
    start = utc(str(protocol["development_start_inclusive_utc"]))
    end = utc(str(protocol["development_end_exclusive_utc"]))
    selected = set(str(item) for item in protocol["markets"])
    rows: list[dict[str, object]] = []
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """;WITH ranked AS (
                 SELECT m.symbol,e.opportunity_id,e.transition_status,e.join_version,
                        e.evidence_sha256,e.evidence_json,e.observed_at_utc,e.event_id,
                        ROW_NUMBER() OVER(PARTITION BY e.opportunity_id
                          ORDER BY e.observed_at_utc DESC,e.event_id DESC) rn
                 FROM app.prospective_opportunity_events e
                 JOIN app.markets m ON m.market_id=e.market_id
                 WHERE m.symbol IN ('EURUSD','GBPUSD','USDJPY'))
               SELECT * FROM ranked WHERE rn=1 ORDER BY symbol,opportunity_id"""
        )
        events = cursor.fetchall()
    for event in events:
        evidence = json.loads(str(event["evidence_json"]))
        decision = utc(str(evidence["decision_at_utc"]))
        if str(event["symbol"]) not in selected or not start <= decision < end:
            continue
        if evidence_sha256(evidence) != str(event["evidence_sha256"]):
            raise ValueError(f"Ledger evidence hash mismatch: {event['opportunity_id']}")
        if str(event["transition_status"]) != "JOINED":
            continue
        rows.append({
            "market": str(event["symbol"]),
            "opportunity_id": str(event["opportunity_id"]),
            "decision_at_utc": evidence["decision_at_utc"],
            "m15_open_utc": evidence["m15_open_utc"],
            "m15_candle_id": evidence["m15_candle_id"],
            "join_version": str(event["join_version"]),
            "atr_snapshot_sha256": evidence["atr_snapshot_sha256"],
            "feature_snapshot_sha256": evidence["feature_snapshot_sha256"],
            "ig_m1_path_sha256": evidence["ig_m1_path_sha256"],
            "ledger_evidence_sha256": str(event["evidence_sha256"]),
        })
    rows.sort(key=lambda row: (row["market"], row["decision_at_utc"], row["opportunity_id"]))
    counts = Counter(str(row["market"]) for row in rows)
    minimum = int(protocol["minimum_joined_per_market"])
    markets = [{"market": market, "joined": counts[market],
                "minimum_met": counts[market] >= minimum}
               for market in sorted(selected)]
    artifact: dict[str, object] = {
        "authority": "IMMUTABLE_NONPROMOTABLE_V4_DEVELOPMENT_COHORT",
        "protocol_sha256": canonical_sha256(protocol),
        "protocol_version": protocol["protocol_version"],
        "development_start_inclusive_utc": protocol["development_start_inclusive_utc"],
        "development_end_exclusive_utc": protocol["development_end_exclusive_utc"],
        "minimum_joined_per_market": minimum,
        "markets": markets,
        "members": rows,
        "economic_outcomes_calculated": False,
        "model_training_performed": False,
        "validation_accessed": False,
        "holdout_accessed": False,
        "model_promotion": "NONE",
        "broker_submission_authority": False,
    }
    artifact["cohort_sha256"] = canonical_sha256(artifact)
    OUTPUT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


if __name__ == "__main__":
    frozen = freeze()
    print(json.dumps({"cohort_sha256": frozen["cohort_sha256"],
                      "markets": frozen["markets"]}, indent=2))
