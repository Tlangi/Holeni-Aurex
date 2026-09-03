from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.model_tournament import run_and_record_tournament  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a non-promotable, development-only Aurex model tournament",
    )
    parser.add_argument(
        "--market", default="USDJPY",
        choices=("ALL", "EURUSD", "GBPUSD", "USDJPY", "GERMANY40", "GBPJPY", "EURJPY", "XAUUSD", "AUDJPY", "USDZAR"),
    )
    parser.add_argument("--notes", default="Audited challenger comparison; no holdout or execution")
    parser.add_argument("--full", action="store_true", help="Print complete candidate evidence")
    arguments = parser.parse_args()
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenant = cursor.fetchone()
    if not tenant:
        raise SystemExit("No tenant exists")
    markets = (
        ("EURUSD", "GBPUSD", "USDJPY", "GERMANY40", "GBPJPY", "EURJPY", "XAUUSD", "AUDJPY", "USDZAR")
        if arguments.market == "ALL" else (arguments.market,)
    )
    results = {}
    for market in markets:
        try:
            result = run_and_record_tournament(
                settings, str(tenant[0]), market, notes=arguments.notes,
            )
            if arguments.full:
                results[market] = result
            else:
                results[market] = {
                    "status": "COMPLETED", "experiment_id": result["experiment_id"],
                    "research_leader": result["research_leader"],
                    "leader_passed_all_development_gates": result["leader_passed_all_development_gates"],
                    "selective_research_leader": result["selective_research_leader"],
                    "candidates": [{
                        "key": item["key"], "auc": item["auc"], "pr_auc": item["pr_auc"],
                        "profit_factor": item["metrics"]["profit_factor"],
                        "expectancy": item["metrics"]["expectancy"],
                        "max_drawdown": item["metrics"]["max_drawdown"],
                        "trade_count": item["metrics"]["trade_count"],
                        "positive_window_fraction": item["positive_window_fraction"],
                        "eligible_for_freeze_research": item["eligible_for_freeze_research"],
                        "failed_gates": [key for key, passed in item["gates"].items() if not passed],
                        "top_features": item["feature_importance"][:5],
                    } for item in result["candidates"]],
                    "promotable": result["promotable"], "holdout_consumed": result["holdout_consumed"],
                    "execution_enabled": result["execution_enabled"],
                }
        except Exception as error:
            results[market] = {"status": "FAILED", "error": str(error),
                               "execution_enabled": False}
    print(json.dumps(results, indent=2, default=str))
