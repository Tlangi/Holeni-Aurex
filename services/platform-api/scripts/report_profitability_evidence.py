"""Print the latest persisted non-promotable USD/JPY and EUR/USD diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402


def main() -> None:
    output: dict[str, object] = {}
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        for symbol in ("USDJPY", "EURUSD"):
            cursor.execute(
                """SELECT TOP (1) e.experiment_id,e.completed_at_utc,d.summary_json,d.decomposition_json
                   FROM app.research_experiments e
                   JOIN app.markets m ON m.market_id=e.market_id
                   JOIN app.research_diagnostics d ON d.experiment_id=e.experiment_id
                   WHERE m.symbol=%s AND e.retrain_type='DIAGNOSTIC_REPLAY'
                     AND e.status='COMPLETED'
                   ORDER BY e.completed_at_utc DESC""",
                (symbol,),
            )
            row = cursor.fetchone()
            if not row:
                output[symbol] = {"status": "NO_DIAGNOSTIC"}
                continue
            decomposition = json.loads(row["decomposition_json"])
            output[symbol] = {
                "experiment_id": str(row["experiment_id"]),
                "completed_at_utc": row["completed_at_utc"].isoformat(),
                "summary": json.loads(row["summary_json"]),
                "decomposition": {
                    key: decomposition.get(key, [])
                    for key in ("direction", "session_name", "trend_regime", "volatility_regime",
                                "confidence_bucket", "exit_reason")
                },
            }
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
