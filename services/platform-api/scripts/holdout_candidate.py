from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.holdout_service import (  # noqa: E402
    EvaluateHoldoutRequest,
    FreezeCandidateRequest,
    evaluate_holdout,
    freeze_candidate,
    read_holdout_status,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Freeze or consume a non-promotable, single-use Aurex holdout",
    )
    parser.add_argument("action", choices=("status", "freeze", "evaluate"))
    parser.add_argument("--market", default="GERMANY40",
                        choices=("EURUSD", "GBPUSD", "USDJPY", "GERMANY40", "GBPJPY", "EURJPY", "XAUUSD", "AUDJPY", "USDZAR"))
    parser.add_argument("--candidate-id")
    parser.add_argument("--holdout-fraction", type=float)
    arguments = parser.parse_args()
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenant = cursor.fetchone()
    if not tenant:
        raise SystemExit("No tenant exists")
    tenant_id = str(tenant[0])
    if arguments.action == "status":
        result = read_holdout_status(settings, tenant_id)
    elif arguments.action == "freeze":
        result = freeze_candidate(
            settings, tenant_id,
            FreezeCandidateRequest(
                market=arguments.market,
                holdout_fraction=arguments.holdout_fraction,
                notes="Owner-requested frozen candidate; broker execution remains disabled",
            ),
        )
    else:
        if not arguments.candidate_id:
            raise SystemExit("--candidate-id is required for evaluate")
        result = evaluate_holdout(
            settings, tenant_id,
            EvaluateHoldoutRequest(candidate_id=arguments.candidate_id),
        )
    print(json.dumps(result, indent=2, default=str))
