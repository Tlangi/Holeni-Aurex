"""Freeze a read-only snapshot of prospective M15 continuity accumulation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.prospective_m15_continuity import SOURCE, summarize_accumulation
from app.research_cohort_eligibility import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_M15_CONTINUITY_PROTOCOL_V1.json"
OUTPUT = ROOT / "docs/audits/AUREX_PROSPECTIVE_M15_CONTINUITY_SNAPSHOT_2026-09-16.json"


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError("Continuity snapshot is immutable; use a new timestamped path")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    results = []
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1 ORDER BY symbol")
        for market in cursor.fetchall():
            cursor.execute("""SELECT candle_id,open_time_utc,close_time_utc,[high],[low],[close],
                                      source,completed,quality_status,is_regular_session,ingested_at_utc
                               FROM app.candles WHERE market_id=%s AND timeframe='M15' AND source=%s
                               ORDER BY open_time_utc""", (str(market["market_id"]), SOURCE))
            rows = cursor.fetchall()
            if rows:
                frame = pd.DataFrame(rows)
                frame.index = pd.DatetimeIndex(frame.pop("open_time_utc"), tz="UTC")
            else:
                frame = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
            evidence = summarize_accumulation(frame, market=market["symbol"])
            results.append(evidence)
    result = {"authority": "IMMUTABLE_PROSPECTIVE_ACCUMULATION_SNAPSHOT",
        "protocol_sha256": canonical_sha256(protocol), "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_rows_rewritten": False, "model_training_performed": False,
        "broker_submission_authority": False, "markets": results}
    result["snapshot_sha256"] = canonical_sha256(result)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot_sha256": result["snapshot_sha256"],
            "markets": [{k: row[k] for k in ("market", "status", "reason", "candle_count",
            "warmed_opportunities", "target_reached") if k in row} for row in results]}, indent=2))


if __name__ == "__main__":
    main()
