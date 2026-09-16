"""Append-only prospective opportunity transitions and training lock."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4


STATUS_BY_REASON = {
    "ATR:": "ATR_PENDING",
    "FEATURE:": "FEATURE_PENDING",
    "FUNDING_BOUNDARY_IN_MAX_HORIZON": "ROLLOVER_BLOCKED",
    "IG_PATH:HORIZON_NOT_YET_COMPLETE": "PATH_PENDING",
    "IG_PATH:": "PATH_BLOCKED",
    "JOINED_TRAINING_INPUT_READY": "JOINED",
}


def transition_status(row: dict[str, object]) -> str:
    reason = str(row["reason"])
    if reason == "JOINED_TRAINING_INPUT_READY":
        return "JOINED"
    if reason == "FUNDING_BOUNDARY_IN_MAX_HORIZON":
        return "ROLLOVER_BLOCKED"
    for prefix in ("ATR:", "FEATURE:", "IG_PATH:HORIZON_NOT_YET_COMPLETE", "IG_PATH:"):
        if reason.startswith(prefix):
            return STATUS_BY_REASON[prefix]
    raise ValueError(f"Unrecognized prospective transition reason: {reason}")


def evidence_sha256(row: dict[str, object]) -> str:
    return sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                             default=str).encode()).hexdigest()


def transition_key(row: dict[str, object], status: str) -> str:
    # One durable event per semantic gate state. Evidence is retained in that event.
    return sha256(f"{row['opportunity_id']}|{status}".encode()).hexdigest()


def append_snapshot_events(connection, snapshot: dict[str, object]) -> dict[str, int]:
    cursor = connection.cursor(as_dict=True)
    cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1")
    market_ids = {row["symbol"]: str(row["market_id"]) for row in cursor.fetchall()}
    inserted = 0
    for row in snapshot["opportunities"]:
        status = transition_status(row)
        digest = evidence_sha256(row)
        key = transition_key(row, status)
        cursor.execute("""IF NOT EXISTS(SELECT 1 FROM app.prospective_opportunity_events WHERE transition_key=%s)
            INSERT app.prospective_opportunity_events(event_id,transition_key,opportunity_id,market_id,
              m15_candle_id,join_version,transition_status,transition_reason,atr_snapshot_sha256,
              feature_snapshot_sha256,ig_m1_path_sha256,evidence_sha256,evidence_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (key, str(uuid4()), key, row["opportunity_id"], market_ids[row["market"]],
             int(row["m15_candle_id"]), snapshot["join_version"], status, row["reason"],
             row.get("atr_snapshot_sha256"), row.get("feature_snapshot_sha256"),
             row.get("ig_m1_path_sha256"), digest,
             json.dumps(row, sort_keys=True, separators=(",", ":"))))
        inserted += max(cursor.rowcount, 0)
    connection.commit()
    cursor.execute("SELECT symbol,joined_opportunities,training_gate_open FROM app.vw_prospective_training_gate ORDER BY symbol")
    gate = cursor.fetchall()
    return {"inserted_events": inserted,
            "joined_opportunities": sum(int(row["joined_opportunities"]) for row in gate),
            "markets_gate_open": sum(bool(row["training_gate_open"]) for row in gate)}


def require_prospective_training_gate(connection, market: str) -> None:
    cursor = connection.cursor(as_dict=True)
    try:
        cursor.execute("SELECT joined_opportunities,training_gate_open FROM app.vw_prospective_training_gate WHERE symbol=%s",
                       (market,))
        row = cursor.fetchone()
    except Exception as exc:
        raise RuntimeError("PROSPECTIVE_TRAINING_GATE_SCHEMA_MISSING") from exc
    if not row or not bool(row["training_gate_open"]):
        count = int(row["joined_opportunities"]) if row else 0
        raise RuntimeError(f"PROSPECTIVE_TRAINING_GATE_BLOCKED:{market}:{count}/30")


def persist_milestone(connection, *, snapshot: dict[str, object], artifact_path: Path) -> bool:
    counts = {row["market"]: row["joined_opportunities"] for row in snapshot["markets"]}
    cursor = connection.cursor(as_dict=True)
    cursor.execute("SELECT TOP 1 joined_counts_json FROM app.prospective_accumulation_milestones ORDER BY created_at_utc DESC")
    previous = cursor.fetchone()
    if previous and json.loads(previous["joined_counts_json"]) == counts:
        return False
    cursor.execute("""INSERT app.prospective_accumulation_milestones
        (milestone_id,snapshot_sha256,artifact_path,joined_counts_json,market_target_reached)
        VALUES(%s,%s,%s,%s,%s)""", (str(uuid4()), snapshot["snapshot_sha256"],
        str(artifact_path), json.dumps(counts, sort_keys=True), int(any(value >= 30 for value in counts.values()))))
    connection.commit()
    return True
