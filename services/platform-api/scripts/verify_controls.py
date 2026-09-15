"""Read-only snapshot of owner engine and strategy controls.

This does not exercise control mutations; use isolated tests for that purpose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402


def read_control_snapshot(settings: object) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT u.tenant_id, ec.mode, ec.new_orders_enabled
               FROM app.users u JOIN app.engine_controls ec ON ec.tenant_id=u.tenant_id
               WHERE u.role='owner' AND u.status='active' ORDER BY u.created_at_utc"""
        )
        owners = cursor.fetchall()
        if not owners:
            return {"status": "unverified", "reason": "No active owner with engine controls", "controls": []}
        controls = []
        for tenant_id, mode, new_orders_enabled in owners:
            cursor.execute(
                "SELECT status, COUNT(*) FROM app.strategies WHERE tenant_id=%s GROUP BY status",
                (tenant_id,),
            )
            controls.append({
                "tenant_id": str(tenant_id),
                "engine_mode": str(mode),
                "new_orders_enabled": bool(new_orders_enabled),
                "strategy_status_counts": {str(status): int(count) for status, count in cursor.fetchall()},
            })
    return {"status": "observed", "verification": "READ_ONLY", "controls": controls}


if __name__ == "__main__":
    print(json.dumps(read_control_snapshot(get_settings()), indent=2))
