from __future__ import annotations

from datetime import timezone

from app.config import Settings
from app.database import open_database


def read_trade_history(settings: Settings, tenant_id: str, *, limit: int = 50) -> dict[str, object]:
    limit = max(1, min(limit, 200))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) position_id,market_symbol,direction,size,entry_price,
                      current_price,unrealised_pnl,pnl_currency,opened_at_utc,closed_at_utc,status
               FROM app.positions
               WHERE tenant_id=%s AND status IN ('CLOSED','RESOLVED')
               ORDER BY COALESCE(closed_at_utc,updated_at_utc) DESC""",
            (limit, tenant_id),
        )
        rows = cursor.fetchall()
    return {
        "trades": [
            {
                "position_id": str(row["position_id"]),
                "market": str(row["market_symbol"]),
                "direction": str(row["direction"]),
                "size": str(row["size"]),
                "entry_price": str(row["entry_price"]),
                "exit_price": str(row["current_price"]) if row["current_price"] is not None else None,
                "last_recorded_pnl": str(row["unrealised_pnl"] or 0),
                "pnl_currency": str(row["pnl_currency"]),
                "opened_at_utc": row["opened_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
                "closed_at_utc": row["closed_at_utc"].replace(tzinfo=timezone.utc).isoformat()
                    if row["closed_at_utc"] else None,
                "status": str(row["status"]),
            }
            for row in rows
        ],
        "count": len(rows),
        "pnl_note": "P/L is the last broker-observed value unless a confirmed close value exists.",
    }
