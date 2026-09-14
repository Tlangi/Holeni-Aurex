"""Read the frozen GBP/USD prediction-to-trade comparison; no model fitting or writes."""
from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.frozen_economic_bridge import compare_frozen_cohort


def main() -> None:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT TOP 1 cohort_id,manifest_sha256,manifest_json,selected_count,
                          valid_ig_outcome_count FROM app.frozen_research_diagnostic_cohorts
                          WHERE market_id=(SELECT market_id FROM app.markets WHERE symbol='GBPUSD')
                          ORDER BY frozen_at_utc DESC""")
        cohort = cursor.fetchone()
        if not cohort:
            raise ValueError("No frozen GBP/USD cohort")
        manifest_text = cohort["manifest_json"]
        manifest = json.loads(manifest_text)
        if sha256(manifest_text.encode()).hexdigest() != cohort["manifest_sha256"]:
            raise ValueError("Frozen manifest hash mismatch")
        cursor.execute("""SELECT prediction_id,outcome_sha256,outcome_json
                          FROM app.frozen_research_prediction_outcomes WHERE cohort_id=%s""",
                       (cohort["cohort_id"],))
        rows = [{"prediction_id": r["prediction_id"], "outcome_sha256": r["outcome_sha256"],
                 "payload": json.loads(r["outcome_json"])} for r in cursor.fetchall()]
    result = compare_frozen_cohort(manifest, rows)
    if result["selected"] != cohort["selected_count"] or result["ig_evaluable"] != cohort["valid_ig_outcome_count"]:
        raise ValueError("Frozen cohort counts mismatch")
    result["cohort_id"] = str(cohort["cohort_id"])
    result["manifest_sha256"] = cohort["manifest_sha256"]
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
