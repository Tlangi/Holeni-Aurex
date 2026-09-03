from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import numpy as np

from app.config import Settings
from app.database import open_database
from app.market_calendar import is_regular_session, operational_session_state
from app.research_regimes import REGIME_VERSION, market_session


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _expected_times(
    start: datetime, end: datetime, interval: int, market: dict[str, object], holidays: set[object],
) -> list[datetime]:
    result: list[datetime] = []
    current = _aware(start)
    finish = _aware(end)
    while current <= finish:
        if is_regular_session(
            current, calendar_code=str(market["calendar_code"]),
            market_timezone=str(market["market_timezone"]),
            session_open=market["session_open_local"], session_close=market["session_close_local"],
            holidays=holidays,
        ):
            result.append(current)
        current += timedelta(minutes=interval)
    return result


def _segment_stats(
    times: list[datetime], interval: int, market: dict[str, object], holidays: set[object],
) -> dict[str, object]:
    ordered = sorted({_aware(value) for value in times})
    if not ordered:
        return {"actual": 0, "expected": 0, "completeness": 0.0, "gaps": [], "largest": 0}
    expected = _expected_times(ordered[0], ordered[-1], interval, market, holidays)
    actual_set = set(ordered)
    missing = [value for value in expected if value not in actual_set]
    groups: list[list[datetime]] = []
    for value in missing:
        if not groups or value - groups[-1][-1] != timedelta(minutes=interval):
            groups.append([value])
        else:
            groups[-1].append(value)
    gaps = [
        {"start": group[0], "end": group[-1], "minutes": len(group) * interval}
        for group in groups
    ]
    return {
        "actual": len(actual_set), "expected": len(expected),
        "completeness": len(actual_set) / len(expected) if expected else 0.0,
        "gaps": gaps, "largest": max((item["minutes"] for item in gaps), default=0),
    }


def _persist_segment(
    cursor: object, market_id: str, provider: str, timeframe: str, start: datetime, end: datetime,
    purpose: str, source_reference: str, stats: dict[str, object], minimum: float,
) -> tuple[str, str]:
    status = "PASS" if int(stats["actual"]) > 0 and float(stats["completeness"]) >= minimum else "WARN"
    cursor.execute(
        """SELECT TOP (1) data_quality_segment_id FROM app.data_quality_segments
           WHERE market_id=%s AND provider=%s AND timeframe=%s AND purpose=%s
             AND segment_start_utc=%s ORDER BY updated_at_utc DESC""",
        (market_id, provider, timeframe, purpose, start),
    )
    existing = cursor.fetchone()
    segment_id = str(existing["data_quality_segment_id"]) if existing else str(uuid4())
    payload = json.dumps({"features_reset_at_gaps": True, "regime_version": REGIME_VERSION})
    if existing:
        cursor.execute(
            """UPDATE app.data_quality_segments SET segment_end_utc=%s,actual_rows=%s,
                      expected_rows=%s,completeness_pct=%s,gap_count=%s,largest_gap_minutes=%s,
                      quality_status=%s,source_reference=%s,details_json=%s,updated_at_utc=SYSUTCDATETIME()
               WHERE data_quality_segment_id=%s""",
            (end, stats["actual"], stats["expected"], float(stats["completeness"]),
             len(stats["gaps"]), stats["largest"], status, source_reference, payload, segment_id),
        )
    else:
        cursor.execute(
            """INSERT app.data_quality_segments
                 (data_quality_segment_id,market_id,provider,timeframe,segment_start_utc,
                  segment_end_utc,expected_interval_minutes,actual_rows,expected_rows,
                  completeness_pct,gap_count,largest_gap_minutes,purpose,quality_status,
                  source_reference,details_json)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (segment_id, market_id, provider, timeframe, start, end,
             5 if timeframe == "M5" else 15, stats["actual"], stats["expected"],
             float(stats["completeness"]), len(stats["gaps"]), stats["largest"],
             purpose, status, source_reference, payload),
        )
    return segment_id, status


def _record_gap(
    cursor: object, market_id: str, timeframe: str, before: str | None, after: str | None,
    start: datetime, end: datetime, classification: str, blocking: bool, reason: str,
) -> None:
    minutes = max(0, int((_aware(end) - _aware(start)).total_seconds() // 60))
    cursor.execute(
        """SELECT TOP (1) data_quality_gap_id FROM app.data_quality_gaps
           WHERE market_id=%s AND timeframe=%s AND gap_start_utc=%s AND gap_end_utc=%s
             AND classification=%s AND resolved_at_utc IS NULL""",
        (market_id, timeframe, start, end, classification),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        """INSERT app.data_quality_gaps
             (data_quality_gap_id,market_id,timeframe,provider_before,provider_after,
              gap_start_utc,gap_end_utc,gap_minutes,classification,execution_blocking,reason)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid4()), market_id, timeframe, before, after, start, end, minutes,
         classification, int(blocking), reason),
    )


def sync_quality_evidence(settings: Settings) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT market_id,symbol,calendar_code,market_timezone,session_open_local,session_close_local
               FROM app.markets WHERE enabled=1 AND research_enabled=1 ORDER BY market_tier,symbol"""
        )
        markets = cursor.fetchall()
        for market in markets:
            market_id = str(market["market_id"])
            cursor.execute(
                "SELECT holiday_date,session_close_local FROM app.market_holidays WHERE calendar_code=%s",
                (market["calendar_code"],),
            )
            holiday_rows = cursor.fetchall()
            holidays = {row["holiday_date"] for row in holiday_rows}
            holiday_schedule = {row["holiday_date"]: row["session_close_local"] for row in holiday_rows}
            session = operational_session_state(
                now, calendar_code=str(market["calendar_code"]),
                market_timezone=str(market["market_timezone"]),
                session_open=market["session_open_local"], session_close=market["session_close_local"],
                holidays=holiday_schedule,
            )
            statuses: dict[str, list[str]] = {"DUKASCOPY": [], "IG": []}
            ig_latest: dict[str, dict[str, object]] = {}
            for provider, pattern, purpose in (
                ("DUKASCOPY", "DUKASCOPY%", "HISTORICAL_RESEARCH"),
                ("IG", "IG%", "LIVE_EXECUTION"),
            ):
                for timeframe, interval in (("M5", 5), ("M15", 15)):
                    cursor.execute(
                        """SELECT open_time_utc,bid_close,ask_close,spread_close,completed,is_regular_session
                           FROM app.candles WHERE market_id=%s AND timeframe=%s AND source LIKE %s
                             AND completed=1 ORDER BY open_time_utc""",
                        (market_id, timeframe, pattern),
                    )
                    rows = cursor.fetchall()
                    regular = [row for row in rows if bool(row["is_regular_session"])]
                    if not regular:
                        continue
                    times = [_aware(row["open_time_utc"]) for row in regular]
                    stats = _segment_stats(times, interval, market, holidays)
                    _, status = _persist_segment(
                        cursor, market_id, provider, timeframe, times[0], times[-1], purpose,
                        pattern, stats, settings.research_segment_minimum_completeness,
                    )
                    statuses[provider].append(status)
                    if provider == "IG":
                        recent = [gap for gap in stats["gaps"] if _aware(gap["end"]) >= now - timedelta(hours=settings.execution_gap_lookback_hours)]
                        for gap in recent[:100]:
                            _record_gap(cursor, market_id, timeframe, "IG", "IG", gap["start"], gap["end"],
                                        "LIVE_STREAM_INTERRUPTION", True, "Expected regular-session IG candle is missing")
                        ig_latest[timeframe] = {"row": regular[-1], "recent_gaps": recent, "stats": stats}

            for timeframe, interval in (("M5", 5), ("M15", 15)):
                cursor.execute(
                    """SELECT MAX(CASE WHEN source LIKE 'DUKASCOPY%%' THEN open_time_utc END) duka_end,
                              MIN(CASE WHEN source LIKE 'IG%%' THEN open_time_utc END) ig_start
                       FROM app.candles WHERE market_id=%s AND timeframe=%s""",
                    (market_id, timeframe),
                )
                boundary = cursor.fetchone() or {}
                if boundary.get("duka_end") and boundary.get("ig_start") and boundary["ig_start"] > boundary["duka_end"] + timedelta(minutes=interval):
                    _record_gap(cursor, market_id, timeframe, "DUKASCOPY", "IG",
                                boundary["duka_end"] + timedelta(minutes=interval),
                                boundary["ig_start"] - timedelta(minutes=interval),
                                "EXPECTED_PROVIDER_BOUNDARY", False,
                                "Declared historical-provider boundary; features must reset")

            m5 = ig_latest.get("M5", {})
            m15 = ig_latest.get("M15", {})
            m5_row = m5.get("row") or {}
            m15_row = m15.get("row") or {}
            latest_m5 = _aware(m5_row["open_time_utc"]) if m5_row else None
            latest_m15 = _aware(m15_row["open_time_utc"]) if m15_row else None
            m5_fresh = bool(latest_m5 and (now - latest_m5).total_seconds() <= settings.execution_m5_fresh_seconds)
            m15_fresh = bool(latest_m15 and (now - latest_m15).total_seconds() <= settings.execution_m15_fresh_seconds)
            quote_fresh = bool(latest_m5 and (now - latest_m5).total_seconds() <= settings.execution_quote_fresh_seconds)
            bid_fresh = quote_fresh and m5_row.get("bid_close") is not None
            ask_fresh = quote_fresh and m5_row.get("ask_close") is not None
            spread_fresh = quote_fresh and m5_row.get("spread_close") is not None
            cursor.execute(
                """SELECT COUNT(*) rule_count FROM app.broker_market_rules
                   WHERE market_id=%s AND observed_at_utc>=DATEADD(second,-%s,SYSUTCDATETIME())""",
                (market_id, settings.broker_rule_fresh_seconds),
            )
            rules_fresh = int(cursor.fetchone()["rule_count"] or 0) > 0
            recent_gaps = len(m5.get("recent_gaps") or []) + len(m15.get("recent_gaps") or [])
            historical = "PASS" if statuses["DUKASCOPY"] and all(value == "PASS" for value in statuses["DUKASCOPY"]) else "WARN"
            training = historical
            if session.should_receive_data:
                recent_continuity = "PASS" if m5_fresh and m15_fresh and recent_gaps == 0 else "FAIL"
                price_freshness = "PASS" if bid_fresh and ask_fresh and spread_fresh else "FAIL"
            else:
                recent_continuity = session.status
                price_freshness = session.status
            cursor.execute(
                """SELECT COUNT(*) boundary_count FROM app.data_quality_gaps
                   WHERE market_id=%s AND classification='EXPECTED_PROVIDER_BOUNDARY' AND resolved_at_utc IS NULL""",
                (market_id,),
            )
            cross_provider = "KNOWN_GAP" if int(cursor.fetchone()["boundary_count"] or 0) else "PASS"
            session_valid = bool(m5_row and m5_row.get("is_regular_session"))
            latest_complete = bool(m5_row and m5_row.get("completed"))
            if not session.should_receive_data:
                overall = session.status
            else:
                overall = "PASS" if all((m5_fresh, m15_fresh, bid_fresh, ask_fresh, spread_fresh,
                                          rules_fresh, session_valid, latest_complete, recent_gaps == 0)) else "FAIL"
            reasons = {
                "m5_latest_utc": latest_m5.isoformat() if latest_m5 else None,
                "m15_latest_utc": latest_m15.isoformat() if latest_m15 else None,
                "known_provider_boundary_is_execution_blocking": False,
                "features_reset_at_boundaries": True,
                "session_status": session.status,
                "session_reason": session.reason,
                "data_expected_now": session.should_receive_data,
                "freshness_is_execution_blocking_now": session.should_receive_data,
            }
            cursor.execute(
                """INSERT app.execution_quality_snapshots
                     (execution_quality_snapshot_id,market_id,m5_fresh,m15_fresh,bid_fresh,
                      ask_fresh,spread_fresh,broker_rules_fresh,market_session_valid,
                      latest_candle_completed,recent_unexpected_gap_count,
                      historical_research_quality,training_quality,recent_ig_continuity,
                      execution_price_freshness,cross_provider_continuity,
                      overall_execution_quality,reasons_json)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), market_id, int(m5_fresh), int(m15_fresh), int(bid_fresh),
                 int(ask_fresh), int(spread_fresh), int(rules_fresh), int(session_valid),
                 int(latest_complete), recent_gaps, historical, training, recent_continuity,
                 price_freshness, cross_provider, overall, json.dumps(reasons)),
            )
            outcomes.append({"symbol": market["symbol"], "historical_research_quality": historical,
                             "recent_ig_continuity": recent_continuity,
                             "cross_provider_continuity": cross_provider,
                             "overall_execution_quality": overall, "recent_unexpected_gaps": recent_gaps})
        connection.commit()
    return outcomes


def _stats(values: np.ndarray) -> dict[str, Decimal | int]:
    return {
        "count": int(len(values)), "mean": Decimal(str(float(np.mean(values)))),
        "median": Decimal(str(float(np.percentile(values, 50)))),
        "p75": Decimal(str(float(np.percentile(values, 75)))),
        "p90": Decimal(str(float(np.percentile(values, 90)))),
        "p95": Decimal(str(float(np.percentile(values, 95)))),
        "maximum": Decimal(str(float(np.max(values)))),
    }


def sync_cost_models(settings: Settings) -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            "SELECT market_id,symbol FROM app.markets WHERE enabled=1 AND research_enabled=1 ORDER BY market_tier,symbol"
        )
        for market in cursor.fetchall():
            market_id, symbol = str(market["market_id"]), str(market["symbol"])
            cursor.execute(
                """SELECT open_time_utc,spread_close FROM app.candles
                   WHERE market_id=%s AND timeframe='M5' AND source LIKE 'IG%%'
                     AND completed=1 AND spread_close IS NOT NULL AND spread_close>=0
                   ORDER BY open_time_utc""", (market_id,),
            )
            rows = cursor.fetchall()
            if not rows:
                outcomes.append({"symbol": symbol, "status": "INSUFFICIENT", "observations": 0})
                continue
            config = {
                "optimistic": settings.cost_model_optimistic_percentile,
                "normal": settings.cost_model_normal_percentile,
                "stressed": settings.cost_model_stressed_percentile,
                "regime_version": REGIME_VERSION,
            }
            digest = hashlib.sha256(json.dumps({"symbol": symbol, "first": str(rows[0]["open_time_utc"]),
                "last": str(rows[-1]["open_time_utc"]), "count": len(rows), **config}, sort_keys=True).encode()).hexdigest()
            version = f"ig-spread-{digest[:12]}"
            cursor.execute("SELECT cost_model_version_id,status FROM app.cost_model_versions WHERE market_id=%s AND version=%s", (market_id, version))
            existing = cursor.fetchone()
            if existing:
                outcomes.append({"symbol": symbol, "status": existing["status"], "version": version,
                                 "observations": len(rows)})
                continue
            status = "CURRENT" if len(rows) >= settings.cost_model_minimum_observations else "INSUFFICIENT"
            model_id = str(uuid4())
            if status == "CURRENT":
                cursor.execute("UPDATE app.cost_model_versions SET status='RETIRED' WHERE market_id=%s AND status='CURRENT'", (market_id,))
            cursor.execute(
                """INSERT app.cost_model_versions
                     (cost_model_version_id,market_id,version,provider,source_start_utc,
                      source_end_utc,observation_count,optimistic_percentile,normal_percentile,
                      stressed_percentile,configuration_hash,status)
                   VALUES(%s,%s,%s,'IG',%s,%s,%s,%s,%s,%s,%s,%s)""",
                (model_id, market_id, version, rows[0]["open_time_utc"], rows[-1]["open_time_utc"],
                 len(rows), settings.cost_model_optimistic_percentile, settings.cost_model_normal_percentile,
                 settings.cost_model_stressed_percentile, digest, status),
            )
            buckets: dict[tuple[str, str], list[float]] = {("OVERALL", "ALL"): []}
            for row in rows:
                value = float(row["spread_close"])
                opened = _aware(row["open_time_utc"])
                session = market_session(symbol, opened)
                quarter = opened.hour * 4 + opened.minute // 15
                for key in (("OVERALL", "ALL"), ("SESSION", session),
                            ("WEEKDAY", str(opened.weekday())), ("QUARTER_HOUR", str(quarter))):
                    buckets.setdefault(key, []).append(value)
            for (bucket_type, key), values in buckets.items():
                evidence = _stats(np.asarray(values, dtype=float))
                cursor.execute(
                    """INSERT app.cost_model_buckets
                         (cost_model_bucket_id,cost_model_version_id,bucket_type,bucket_key,
                          session_name,weekday_number,quarter_hour,volatility_regime,
                          observation_count,mean_spread,median_spread,p75_spread,p90_spread,
                          p95_spread,max_spread)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s)""",
                    (str(uuid4()), model_id, bucket_type, key, key if bucket_type == "SESSION" else None,
                     int(key) if bucket_type == "WEEKDAY" else None,
                     int(key) if bucket_type == "QUARTER_HOUR" else None,
                     evidence["count"], evidence["mean"], evidence["median"], evidence["p75"],
                     evidence["p90"], evidence["p95"], evidence["maximum"]),
                )
            outcomes.append({"symbol": symbol, "status": status, "version": version,
                             "observations": len(rows), "overall": {k: str(v) for k, v in _stats(np.asarray(buckets[("OVERALL", "ALL")])).items()}})
        connection.commit()
    return outcomes


def read_research_evidence(settings: Settings) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """WITH ranked AS (SELECT e.*,ROW_NUMBER() OVER(PARTITION BY e.market_id ORDER BY e.evaluated_at_utc DESC) rn
               FROM app.execution_quality_snapshots e)
               SELECT m.symbol,r.* FROM ranked r JOIN app.markets m ON m.market_id=r.market_id
               WHERE r.rn=1 ORDER BY m.symbol"""
        )
        execution = cursor.fetchall()
        cursor.execute(
            """WITH ranked AS (SELECT c.*,ROW_NUMBER() OVER(PARTITION BY c.market_id ORDER BY c.created_at_utc DESC) rn
               FROM app.cost_model_versions c)
               SELECT m.symbol,r.cost_model_version_id,r.version,r.observation_count,r.status,r.source_start_utc,r.source_end_utc
               FROM ranked r JOIN app.markets m ON m.market_id=r.market_id WHERE r.rn=1 ORDER BY m.symbol"""
        )
        costs = cursor.fetchall()
    def serialise(row: dict[str, object]) -> dict[str, object]:
        return {key: (value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value, datetime) else
                      bool(value) if isinstance(value, bool) else str(value) if isinstance(value, Decimal) else value)
                for key, value in row.items()}
    return {"execution_quality": [serialise(row) for row in execution],
            "cost_models": [serialise(row) for row in costs]}
