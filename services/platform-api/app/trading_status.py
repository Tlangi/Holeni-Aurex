from __future__ import annotations

from app.config import Settings
from app.database import open_database


def read_trading_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT mode,new_orders_enabled,pause_reason,changed_at_utc
               FROM app.engine_controls WHERE tenant_id=%s""",
            (tenant_id,),
        )
        control = cursor.fetchone() or {}
        cursor.execute(
            """SELECT status,COUNT(*) AS item_count FROM app.model_versions
               GROUP BY status ORDER BY status"""
        )
        model_counts = {str(row["status"]): int(row["item_count"]) for row in cursor.fetchall()}
        cursor.execute(
            """SELECT m.symbol,COUNT(c.candle_id) AS candle_count,MAX(c.open_time_utc) AS latest_candle_utc
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id AND c.completed=1
               WHERE m.enabled=1 GROUP BY m.symbol ORDER BY m.symbol"""
        )
        markets = [
            {
                "symbol": str(row["symbol"]),
                "completed_candles": int(row["candle_count"]),
                "latest_candle_utc": row["latest_candle_utc"].isoformat() if row["latest_candle_utc"] else None,
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(
            """SELECT
                 SUM(CASE WHEN status='WOULD_SUBMIT' THEN 1 ELSE 0 END) AS shadow_intents,
                 SUM(CASE WHEN status IN ('SUBMITTED','CONFIRMING','OPEN') THEN 1 ELSE 0 END) AS active_intents
               FROM app.order_intents WHERE tenant_id=%s""",
            (tenant_id,),
        )
        intents = cursor.fetchone() or {}

    return {
        "environment": "DEMO",
        "mode": control.get("mode", "PAUSED"),
        "new_orders_enabled": bool(control.get("new_orders_enabled", False)),
        "pause_reason": control.get("pause_reason"),
        "models": model_counts,
        "markets": markets,
        "shadow_intents": int(intents.get("shadow_intents") or 0),
        "active_intents": int(intents.get("active_intents") or 0),
        "gates": {
            "live_trading_supported": False,
            "requires_validated_model": True,
            "requires_fresh_market_data": True,
            "requires_stop_and_take_profit": True,
            "requires_resolved_reconciliation": True,
        },
    }
