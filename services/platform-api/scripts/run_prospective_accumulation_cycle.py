"""Run one idempotent prospective-ledger transition cycle."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings
from app.database import open_database
from app.prospective_accumulation import append_snapshot_events, persist_milestone
from scripts.snapshot_prospective_joined_opportunities import ROOT, collect_snapshot


def run_cycle() -> dict[str, object]:
    snapshot = collect_snapshot()
    settings = get_settings()
    with open_database(settings, query_timeout_seconds=120) as connection:
        event_result = append_snapshot_events(connection, snapshot)
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT TOP 1 joined_counts_json FROM app.prospective_accumulation_milestones ORDER BY created_at_utc DESC")
        previous = cursor.fetchone()
        counts = {row["market"]: row["joined_opportunities"] for row in snapshot["markets"]}
        milestone_needed = not previous or json.loads(previous["joined_counts_json"]) != counts
        artifact_path = None
        if milestone_needed:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            artifact_path = ROOT / "docs/audits" / (
                f"AUREX_PROSPECTIVE_ACCUMULATION_MILESTONE_{stamp}_{snapshot['snapshot_sha256'][:12]}.json")
            if artifact_path.exists():
                raise FileExistsError("Milestone artifact collision")
            artifact_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            if not persist_milestone(connection, snapshot=snapshot, artifact_path=artifact_path):
                raise RuntimeError("Milestone changed during persistence")
    return {**event_result, "snapshot_sha256": snapshot["snapshot_sha256"],
            "milestone_created": artifact_path is not None,
            "milestone_path": str(artifact_path) if artifact_path else None}


if __name__ == "__main__":
    print(json.dumps(run_cycle(), indent=2))
