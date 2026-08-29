from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.research_service import ResearchReplayRequest, run_research_replay  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run non-promotable, non-executing Aurex strategy diagnostics",
    )
    parser.add_argument(
        "--market", default="ALL",
        choices=("ALL", "EURUSD", "GBPUSD", "USDJPY", "GERMANY40"),
    )
    parser.add_argument("--max-candles", type=int, default=100000)
    parser.add_argument(
        "--cost-model", default="NORMAL",
        choices=("OPTIMISTIC", "NORMAL", "STRESSED"),
    )
    arguments = parser.parse_args()
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenant = cursor.fetchone()
    if not tenant:
        raise SystemExit("No tenant exists")
    markets = (
        ("EURUSD", "GBPUSD", "USDJPY", "GERMANY40")
        if arguments.market == "ALL" else (arguments.market,)
    )
    results = {}
    for market in markets:
        try:
            result = run_research_replay(
                settings,
                str(tenant[0]),
                ResearchReplayRequest(
                    market=market,
                    max_candles=arguments.max_candles,
                    cost_model=arguments.cost_model,
                ),
            )
            results[market] = {
                "status": result["status"],
                "experiment_id": result["experiment_id"],
                "replay_run_id": result["replay_run_id"],
                "summary": result["summary"],
                "promotable": result["promotable"],
                "execution_enabled": result["execution_enabled"],
            }
        except Exception as error:  # continue so each market has an audited outcome
            results[market] = {"status": "FAILED", "error": str(error)}
    print(json.dumps(results, indent=2, default=str))

