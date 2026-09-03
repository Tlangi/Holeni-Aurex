from __future__ import annotations

from app.config import Settings
from app.database import open_database


def read_daily_shadow_performance(settings: Settings, tenant_id: str, days: int = 30) -> dict[str, object]:
    days = max(1, min(days, 365))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """WITH dates AS (
                 SELECT CAST(DATEADD(day,-v.number,CAST(SYSUTCDATETIME() AS date)) AS date) evidence_date
                 FROM master..spt_values v WHERE v.type='P' AND v.number<%s
               ), markets AS (SELECT market_id,symbol FROM app.markets WHERE enabled=1),
               trades AS (
                 SELECT market_id,CAST(opened_at_utc AS date) evidence_date,
                   COUNT(*) opened_count,SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) closed_count,
                   SUM(CASE WHEN realized_pnl_zar>0 THEN 1 ELSE 0 END) wins,
                   SUM(CASE WHEN realized_pnl_zar<0 THEN 1 ELSE 0 END) losses,
                   SUM(COALESCE(realized_pnl_zar,0)) net_pnl,AVG(net_r_multiple) average_net_r,
                   MAX(max_favourable_excursion_zar) maximum_mfe,MAX(max_adverse_excursion_zar) maximum_mae
                 FROM app.shadow_trades WHERE tenant_id=%s GROUP BY market_id,CAST(opened_at_utc AS date)
               ), candidates AS (
                 SELECT market_id,CAST(created_at_utc AS date) evidence_date,COUNT(*) candidate_count,
                   SUM(CASE WHEN decision='REJECTED' THEN 1 ELSE 0 END) rejected_count
                 FROM app.shadow_candidates WHERE tenant_id=%s GROUP BY market_id,CAST(created_at_utc AS date)
               )
               SELECT d.evidence_date,m.symbol,COALESCE(c.candidate_count,0) candidate_count,
                 COALESCE(c.rejected_count,0) rejected_count,COALESCE(t.opened_count,0) opened_count,
                 COALESCE(t.closed_count,0) closed_count,COALESCE(t.wins,0) wins,
                 COALESCE(t.losses,0) losses,COALESCE(t.net_pnl,0) net_pnl,t.average_net_r,
                 COALESCE(t.maximum_mfe,0) maximum_mfe,COALESCE(t.maximum_mae,0) maximum_mae
               FROM dates d CROSS JOIN markets m
               LEFT JOIN trades t ON t.market_id=m.market_id AND t.evidence_date=d.evidence_date
               LEFT JOIN candidates c ON c.market_id=m.market_id AND c.evidence_date=d.evidence_date
               ORDER BY d.evidence_date DESC,m.symbol""",
            (days, tenant_id, tenant_id),
        )
        rows = cursor.fetchall()
    return {"days": days, "zero_trade_days_included": True, "execution_enabled": False,
            "daily": [{key: (value.isoformat() if key == "evidence_date" else value)
                       for key, value in row.items()} for row in rows]}
