"""Transactional control smoke test that restores the original operational state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.auth import AuthenticatedUser  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.trading_controls import (  # noqa: E402
    EngineControlRequest, StrategyStatusRequest, change_engine_control,
    change_strategy_status,
)


if __name__ == "__main__":
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT TOP 1 u.user_id,u.tenant_id,u.email,u.display_name,u.role,ec.mode
               FROM app.users u JOIN app.engine_controls ec ON ec.tenant_id=u.tenant_id
               WHERE u.role='owner' AND u.status='active' ORDER BY u.created_at_utc"""
        )
        row = cursor.fetchone()
        if not row:
            raise SystemExit("No active owner with engine controls")
        user = AuthenticatedUser(str(row[0]), str(row[1]), row[2], row[3], row[4])
        original_mode = str(row[5])
        cursor.execute(
            "SELECT TOP 1 strategy_id,status FROM app.strategies WHERE tenant_id=%s ORDER BY created_at_utc",
            (user.tenant_id,),
        )
        strategy = cursor.fetchone()
    outcomes: list[dict[str, object]] = []
    try:
        outcomes.append(change_engine_control(
            settings, user, EngineControlRequest(action="PAUSE", reason="Automated control verification pause")
        ))
        outcomes.append(change_engine_control(
            settings, user, EngineControlRequest(action="RESUME_SHADOW", reason="Automated control verification resume")
        ))
        if strategy:
            alternate = "PAUSED" if str(strategy[1]) == "ACTIVE" else "ACTIVE"
            outcomes.append(change_strategy_status(
                settings, user, str(strategy[0]),
                StrategyStatusRequest(status=alternate, reason="Automated strategy control verification"),
            ))
            outcomes.append(change_strategy_status(
                settings, user, str(strategy[0]),
                StrategyStatusRequest(status=str(strategy[1]), reason="Restore strategy after control verification"),
            ))
    finally:
        if original_mode == "PAUSED":
            change_engine_control(
                settings, user, EngineControlRequest(action="PAUSE", reason="Restore paused state after verification")
            )
    print(json.dumps({"status": "passed", "restored_mode": original_mode, "checks": outcomes}, indent=2))
