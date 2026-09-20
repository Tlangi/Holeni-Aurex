"""Read-only, session-aware preopen check; does not arm or submit trades."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.market_calendar import operational_session_state


def main() -> None:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT component_code,status,status_detail,checked_at_utc
                          FROM app.platform_components ORDER BY component_code""")
        components = [{"code": r["component_code"], "status": r["status"],
                       "detail": r["status_detail"],
                       "checked_at_utc": r["checked_at_utc"].isoformat() if r["checked_at_utc"] else None}
                      for r in cursor.fetchall()]
        cursor.execute("""SELECT alert_key,severity,status,last_seen_at_utc
                          FROM app.operational_alerts WHERE status='OPEN'
                          ORDER BY severity,alert_key""")
        alerts = [{"key": r["alert_key"], "severity": r["severity"],
                   "last_seen_at_utc": r["last_seen_at_utc"].isoformat() if r["last_seen_at_utc"] else None}
                  for r in cursor.fetchall()]
        cursor.execute("""SELECT mode,new_orders_enabled,pause_reason
                          FROM app.engine_controls ORDER BY changed_at_utc DESC""")
        controls = [{"mode": r["mode"], "new_orders_enabled": bool(r["new_orders_enabled"]),
                     "pause_reason": r["pause_reason"]} for r in cursor.fetchall()]
        cursor.execute("""SELECT m.market_id,m.symbol,m.calendar_code,m.market_timezone,
                          m.session_open_local,m.session_close_local,
                          (SELECT MAX(c.open_time_utc) FROM app.candles c
                           WHERE c.market_id=m.market_id AND c.timeframe='M1'
                             AND c.completed=1 AND c.source LIKE 'IG_LIGHTSTREAMER%%') latest_ig_m1,
                          (SELECT MAX(c.open_time_utc) FROM app.candles c
                           WHERE c.market_id=m.market_id AND c.timeframe='M5'
                             AND c.completed=1 AND c.source LIKE 'IG_LIGHTSTREAMER%%') latest_ig_m5,
                          (SELECT MAX(l.updated_at_utc) FROM app.live_candle_snapshots l
                           WHERE l.market_id=m.market_id AND l.timeframe='M5') live_m5_updated
                          FROM app.markets m WHERE m.enabled=1 ORDER BY m.symbol""")
        market_rows = cursor.fetchall()
        markets = []
        for r in market_rows:
            cursor.execute("""SELECT holiday_date,session_close_local FROM app.market_holidays
                              WHERE calendar_code=%s""", (r["calendar_code"],))
            holidays = {h["holiday_date"]: h["session_close_local"] for h in cursor.fetchall()}
            session = operational_session_state(
                now, calendar_code=r["calendar_code"], market_timezone=r["market_timezone"],
                session_open=r["session_open_local"], session_close=r["session_close_local"],
                symbol=str(r["symbol"]),
                holidays=holidays)
            markets.append({"symbol": r["symbol"], "session": session.status,
                            "session_reason": session.reason,
                            "expects_data_now": session.should_receive_data,
                            "session_open_utc": session.session_open_utc.isoformat()
                                if session.session_open_utc else None,
                            "grace_until_utc": session.grace_until_utc.isoformat()
                                if session.grace_until_utc else None,
                            "latest_ig_m1_utc": r["latest_ig_m1"].isoformat()
                                if r["latest_ig_m1"] else None,
                            "latest_ig_m5_utc": r["latest_ig_m5"].isoformat()
                                if r["latest_ig_m5"] else None,
                            "live_m5_updated_utc": r["live_m5_updated"].isoformat()
                                if r["live_m5_updated"] else None})
        cursor.execute("""SELECT COUNT(*) pending FROM app.trade_proposals
                          WHERE status='PENDING_OWNER' AND expires_at_utc>SYSUTCDATETIME()""")
        pending = int(cursor.fetchone()["pending"] or 0)
        cursor.execute("""SELECT COUNT(*) unresolved FROM app.order_intents
                          WHERE status IN ('SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED')""")
        unresolved = int(cursor.fetchone()["unresolved"] or 0)
        cursor.execute("""SELECT COUNT(DISTINCT market_id) authoritative_markets
                          FROM app.broker_market_rules WHERE size_increment_authoritative=1""")
        authoritative = int(cursor.fetchone()["authoritative_markets"] or 0)
        cursor.execute("""SELECT TOP (1) status,backup_completed_at_utc,restore_verified_at_utc
                          FROM app.backup_verifications ORDER BY created_at_utc DESC""")
        backup = cursor.fetchone()
        cursor.execute("""SELECT status,COUNT(*) item_count FROM app.research_jobs
                          GROUP BY status ORDER BY status""")
        research_jobs = {str(r["status"]): int(r["item_count"]) for r in cursor.fetchall()}
        cursor.execute("""SELECT TOP (3) job_type,status,created_at_utc,completed_at_utc
                          FROM app.research_jobs ORDER BY created_at_utc DESC""")
        latest_research_jobs = [
            {"job_type": r["job_type"], "status": r["status"],
             "created_at_utc": r["created_at_utc"].isoformat() if r["created_at_utc"] else None,
             "completed_at_utc": r["completed_at_utc"].isoformat() if r["completed_at_utc"] else None}
            for r in cursor.fetchall()]
    print(json.dumps({"checked_at_utc": now.isoformat(),
                      "configured_trading_mode": settings.trading_mode,
                      "demo_execution_configured": settings.demo_execution_configured,
                      "live_allowed": settings.allow_live_trading,
                      "components": components, "open_alerts": alerts,
                      "engine_controls": controls, "markets": markets,
                      "pending_proposals": pending, "unresolved_intents": unresolved,
                      "markets_with_authoritative_increment": authoritative,
                      "latest_backup": {"status": backup["status"],
                                        "backup_completed_at_utc": backup["backup_completed_at_utc"].isoformat()
                                            if backup["backup_completed_at_utc"] else None,
                                        "restore_verified_at_utc": backup["restore_verified_at_utc"].isoformat()
                                            if backup["restore_verified_at_utc"] else None}
                          if backup else None,
                      "research_job_counts": research_jobs,
                      "latest_research_jobs": latest_research_jobs},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
