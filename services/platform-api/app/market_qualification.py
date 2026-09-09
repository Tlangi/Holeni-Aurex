from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import Settings
from app.database import open_database


def qualify_markets(settings: Settings, *, persist: bool = True) -> dict[str, object]:
    """Calculate independent realtime, research, shadow and execution qualifications."""
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.market_id,m.symbol,m.market_tier,m.research_enabled,m.training_enabled,
                      m.signal_enabled,m.demo_trading_enabled,
                      qm.timeframe,c15.latest_time_utc,c5.latest_m5_utc,
                      qm.duplicate_count,qm.missing_period_count,
                      qm.invalid_ohlc_count,qm.details_json,qm.evaluated_at_utc,
                      r.observed_at_utc broker_rule_observed_at_utc,r.market_status,
                      r.size_increment_authoritative,r.size_increment_source
               FROM app.markets m
               OUTER APPLY (SELECT TOP (1) q.timeframe,q.latest_time_utc,q.duplicate_count,
                   q.missing_period_count,q.invalid_ohlc_count,q.details_json,q.evaluated_at_utc
                   FROM app.market_data_quality_runs q WHERE q.market_id=m.market_id
                   AND q.timeframe='M15' ORDER BY q.evaluated_at_utc DESC) qm
               OUTER APPLY (SELECT MAX(open_time_utc) latest_time_utc FROM app.candles c
                   WHERE c.market_id=m.market_id AND c.timeframe='M15' AND c.completed=1) c15
               OUTER APPLY (SELECT MAX(open_time_utc) latest_m5_utc FROM app.candles c
                   WHERE c.market_id=m.market_id AND c.timeframe='M5' AND c.completed=1) c5
               OUTER APPLY (SELECT TOP (1) observed_at_utc,market_status,
                   size_increment_authoritative,size_increment_source
                   FROM app.broker_market_rules br WHERE br.market_id=m.market_id
                   ORDER BY observed_at_utc DESC) r
               WHERE m.enabled=1 ORDER BY m.symbol"""
        )
        rows = cursor.fetchall()
        results = []
        now = datetime.now(timezone.utc)
        for row in rows:
            details = json.loads(str(row.get("details_json") or "{}"))
            recent_gaps = int(details.get("recent_missing_period_count") or 0)
            completeness = float(details.get("regular_session_completeness") or 0)
            provider_diag = details.get("provider_diagnostics") or {}
            boundaries = max(0, len(provider_diag) - 1)
            latest = row.get("latest_time_utc")
            age = (now - latest.replace(tzinfo=timezone.utc)).total_seconds() if latest else None
            m15_fresh = age is not None and age <= settings.execution_m15_fresh_seconds
            latest_m5 = row.get("latest_m5_utc")
            m5_age = (now - latest_m5.replace(tzinfo=timezone.utc)).total_seconds() if latest_m5 else None
            m5_fresh = m5_age is not None and m5_age <= settings.execution_m5_fresh_seconds
            integrity_clean = (
                int(row.get("invalid_ohlc_count") or 0) == 0
                and int(row.get("duplicate_count") or 0) == 0
            )
            gap_policy_pass = completeness >= settings.research_segment_minimum_completeness
            realtime = m5_fresh and m15_fresh and integrity_clean and gap_policy_pass
            research = completeness >= settings.research_segment_minimum_completeness
            training = bool(row["training_enabled"]) and research
            shadow = realtime and research and bool(row["signal_enabled"])
            broker_fresh = bool(row.get("broker_rule_observed_at_utc")) and (
                now - row["broker_rule_observed_at_utc"].replace(tzinfo=timezone.utc)
            ).total_seconds() <= settings.broker_rule_fresh_seconds
            increment_authoritative = bool(row.get("size_increment_authoritative"))
            execution = (shadow and broker_fresh and increment_authoritative
                         and bool(row["demo_trading_enabled"]) and settings.demo_execution_configured)
            reasons = []
            if not m5_fresh: reasons.append("M5_STALE")
            if not m15_fresh: reasons.append("M15_STALE")
            if recent_gaps and not gap_policy_pass: reasons.append("RECENT_GAPS_BELOW_COMPLETENESS_POLICY")
            if not research: reasons.append("HISTORICAL_COMPLETENESS_BELOW_THRESHOLD")
            if not broker_fresh: reasons.append("BROKER_RULES_STALE")
            if not increment_authoritative: reasons.append("SIZE_INCREMENT_NOT_AUTHORITATIVE")
            if not settings.demo_execution_configured: reasons.append("EXECUTION_OPT_IN_DISABLED")
            item = {
                "market_id": str(row["market_id"]), "symbol": row["symbol"],
                "recent_feed_status": "PASS" if realtime else "FAIL",
                "m5_freshness": "PASS" if m5_fresh else "FAIL",
                "m15_freshness": "PASS" if m15_fresh else "FAIL",
                "recent_gap_count": recent_gaps,
                "gaps_acknowledged": recent_gaps > 0,
                "gap_policy_pass": gap_policy_pass,
                "historical_gap_count": int(row.get("missing_period_count") or 0),
                "historical_session_completeness": completeness,
                "largest_gap": details.get("largest_gap"),
                "duplicate_count": int(row.get("duplicate_count") or 0),
                "invalid_ohlc_count": int(row.get("invalid_ohlc_count") or 0),
                "provider_boundary_count": boundaries,
                "realtime_ready": realtime, "research_ready": research,
                "training_eligible": training, "shadow_trading_eligible": shadow,
                "execution_eligible": execution,
                "size_increment_authoritative": increment_authoritative,
                "size_increment_source": row.get("size_increment_source"),
                "qualification_reason": "READY" if not reasons else ";".join(reasons),
                "evaluated_at_utc": now.isoformat(),
            }
            results.append(item)
            if persist:
                cursor.execute(
                    """INSERT app.market_qualification_snapshots
                       (market_qualification_snapshot_id,market_id,recent_feed_status,m5_freshness,
                        m15_freshness,recent_gap_count,historical_gap_count,
                        historical_session_completeness,duplicate_count,invalid_ohlc_count,
                        provider_boundary_count,realtime_ready,research_ready,training_eligible,
                        shadow_trading_eligible,execution_eligible,qualification_reason)
                       VALUES(NEWID(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (item["market_id"], item["recent_feed_status"], item["m5_freshness"],
                     item["m15_freshness"], recent_gaps, item["historical_gap_count"], completeness,
                     item["duplicate_count"], item["invalid_ohlc_count"], boundaries,
                     realtime, research, training, shadow, execution, item["qualification_reason"]),
                )
        if persist:
            connection.commit()
    return {"markets": results, "execution_enabled": False}
