from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.model_governance import feature_complete_rows
from app.ig_demo import IGDemoClient, IGDemoUnavailable
from app.forward_promotion import evaluate_forward_shadow
from app.market_data import _midpoint, _timestamp
from app.market_calendar import is_regular_session


def _persist_m5(settings: Settings, market_id: str, prices: list[dict[str, object]]) -> dict[str, int]:
    accepted = rejected = 0
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT calendar_code,market_timezone,session_open_local,session_close_local
               FROM app.markets WHERE market_id=%s""", (market_id,),
        )
        schedule = cursor.fetchone()
        if not schedule:
            raise ValueError("Unknown market calendar")
        cursor.execute(
            "SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s",
            (str(schedule["calendar_code"]),),
        )
        holidays = {row["holiday_date"] for row in cursor.fetchall()}
        try:
            for candle in prices:
                try:
                    opened = _timestamp(candle.get("snapshotTimeUTC") or candle.get("snapshotTime"))
                    values = [_midpoint(candle[name]) for name in ("openPrice", "highPrice", "lowPrice", "closePrice")]
                    bids = [Decimal(str(candle[name].get("bid"))) for name in ("openPrice", "highPrice", "lowPrice", "closePrice")]
                    asks = [Decimal(str(candle[name].get("ask"))) for name in ("openPrice", "highPrice", "lowPrice", "closePrice")]
                    if opened > datetime.now(timezone.utc) or any(value <= 0 for value in values):
                        raise ValueError("invalid candle time or price")
                    if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
                        raise ValueError("invalid OHLC")
                    cursor.execute(
                        """MERGE app.candles AS target
                           USING (SELECT %s market_id,'M5' timeframe,%s open_time_utc) AS source
                           ON target.market_id=source.market_id AND target.timeframe=source.timeframe
                              AND target.open_time_utc=source.open_time_utc
                           WHEN MATCHED AND target.bid_close IS NULL THEN UPDATE SET
                             bid_open=%s,bid_high=%s,bid_low=%s,bid_close=%s,
                             ask_open=%s,ask_high=%s,ask_low=%s,ask_close=%s,
                             spread_open=%s,spread_close=%s,is_regular_session=%s
                           WHEN NOT MATCHED THEN INSERT
                             (market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],
                              bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                              spread_open,spread_close,is_regular_session,tick_count,source,completed,quality_status)
                           VALUES(source.market_id,source.timeframe,source.open_time_utc,%s,%s,%s,%s,%s,
                                  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                  'IG_DEMO_HISTORICAL',1,'PASS');""",
                        (
                            market_id, opened, *bids, *asks, asks[0]-bids[0], asks[3]-bids[3],
                            is_regular_session(
                                opened, calendar_code=str(schedule["calendar_code"]),
                                market_timezone=str(schedule["market_timezone"]),
                                session_open=schedule["session_open_local"],
                                session_close=schedule["session_close_local"],
                                holidays=holidays,
                            ),
                            opened + timedelta(minutes=5), *values, *bids, *asks,
                            asks[0]-bids[0], asks[3]-bids[3],
                            is_regular_session(
                                opened, calendar_code=str(schedule["calendar_code"]),
                                market_timezone=str(schedule["market_timezone"]),
                                session_open=schedule["session_open_local"],
                                session_close=schedule["session_close_local"],
                                holidays=holidays,
                            ), int(candle.get("lastTradedVolume") or 0),
                        ),
                    )
                    accepted += 1
                except (KeyError, TypeError, ValueError):
                    rejected += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"accepted": accepted, "rejected": rejected}


def aggregate_m15_history(settings: Settings, market_id: str) -> int:
    inserted = 0
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT open_time_utc,[open],high,low,[close],tick_count
               FROM app.candles WHERE market_id=%s AND timeframe='M5' AND completed=1
                 AND quality_status='PASS' ORDER BY open_time_utc""", (market_id,),
        )
        buckets: dict[datetime, list[dict[str, object]]] = {}
        for row in cursor.fetchall():
            opened = row["open_time_utc"]
            bucket = opened.replace(minute=(opened.minute // 15) * 15, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(row)
        for bucket, rows in buckets.items():
            rows.sort(key=lambda item: item["open_time_utc"])
            expected = [bucket + timedelta(minutes=value) for value in (0, 5, 10)]
            if len(rows) != 3 or [item["open_time_utc"] for item in rows] != expected:
                continue
            cursor.execute(
                """IF NOT EXISTS(SELECT 1 FROM app.candles WHERE market_id=%s AND timeframe='M15' AND open_time_utc=%s)
                   BEGIN INSERT app.candles
                     (market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],tick_count,
                      source,completed,quality_status)
                   VALUES(%s,'M15',%s,%s,%s,%s,%s,%s,%s,'IG_HISTORICAL_AGGREGATE',1,'PASS') END""",
                (market_id, bucket, market_id, bucket, bucket + timedelta(minutes=15), rows[0]["open"],
                 max(item["high"] for item in rows), min(item["low"] for item in rows), rows[-1]["close"],
                 sum(int(item["tick_count"] or 0) for item in rows)),
            )
            inserted += max(cursor.rowcount, 0)
        connection.commit()
    return inserted


def _provider_family(source: object) -> str:
    value = str(source or "UNKNOWN").upper()
    if value.startswith("DUKASCOPY"):
        return "DUKASCOPY"
    if value.startswith("IG"):
        return "IG"
    return value


def _combined_validation_status(*, failures: int, recent_missing: int) -> str:
    """Classify the combined view without treating provider boundaries as defects.

    Provider-specific historical completeness is governed by
    ``app.data_quality_segments``. This combined diagnostic still blocks corrupt
    candles and warns about interruptions inside the currently observed ranges.
    """
    if failures:
        return "FAIL"
    if recent_missing:
        return "WARN"
    return "PASS"


def validate_market_data(settings: Settings, market_id: str, timeframe: str) -> dict[str, object]:
    minutes = 5 if timeframe == "M5" else 15
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT calendar_code,market_timezone,session_open_local,session_close_local
               FROM app.markets WHERE market_id=%s""", (market_id,),
        )
        schedule = cursor.fetchone()
        if not schedule:
            raise ValueError("Unknown market calendar")
        cursor.execute(
            "SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s",
            (str(schedule["calendar_code"]),),
        )
        holidays = {row["holiday_date"] for row in cursor.fetchall()}
        cursor.execute(
            """SELECT open_time_utc,close_time_utc,[open],high,low,[close],completed,source
               FROM app.candles WHERE market_id=%s AND timeframe=%s ORDER BY open_time_utc""",
            (market_id, timeframe),
        )
        rows = cursor.fetchall()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        invalid = nonpositive = future = partial = missing = recent_missing = observed_regular = 0
        recent_cutoff = now - timedelta(hours=24)
        provider_rows: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            values = [Decimal(str(row[name])) for name in ("open", "high", "low", "close")]
            invalid += int(values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]))
            nonpositive += int(any(value <= 0 for value in values))
            future += int(row["open_time_utc"] > now)
            partial += int(not row["completed"] or row["close_time_utc"] <= row["open_time_utc"])
            if is_regular_session(
                row["open_time_utc"].replace(tzinfo=timezone.utc),
                calendar_code=str(schedule["calendar_code"]),
                market_timezone=str(schedule["market_timezone"]),
                session_open=schedule["session_open_local"],
                session_close=schedule["session_close_local"], holidays=holidays,
            ):
                observed_regular += 1
                provider_rows.setdefault(_provider_family(row["source"]), []).append(row)

        provider_diagnostics: dict[str, dict[str, object]] = {}
        for provider, segment in provider_rows.items():
            segment_missing = segment_recent_missing = 0
            previous = None
            for row in segment:
                if previous is None:
                    previous = row["open_time_utc"]
                    continue
                candidate = previous + timedelta(minutes=minutes)
                while candidate < row["open_time_utc"]:
                    if is_regular_session(
                        candidate.replace(tzinfo=timezone.utc),
                        calendar_code=str(schedule["calendar_code"]),
                        market_timezone=str(schedule["market_timezone"]),
                        session_open=schedule["session_open_local"],
                        session_close=schedule["session_close_local"], holidays=holidays,
                    ):
                        missing += 1
                        segment_missing += 1
                        is_recent = int(candidate >= recent_cutoff)
                        recent_missing += is_recent
                        segment_recent_missing += is_recent
                    candidate += timedelta(minutes=minutes)
                previous = row["open_time_utc"]
            provider_diagnostics[provider] = {
                "observed_regular_count": len(segment),
                "missing_period_count": segment_missing,
                "recent_missing_period_count": segment_recent_missing,
            }
        failures = invalid + nonpositive + future + partial
        expected_regular = observed_regular + missing
        completeness = observed_regular / expected_regular if expected_regular else 0.0
        status = _combined_validation_status(failures=failures, recent_missing=recent_missing)
        result = {
            "candle_count": len(rows), "duplicate_count": 0, "missing_period_count": missing,
            "recent_missing_period_count": recent_missing,
            "regular_session_observed_count": observed_regular,
            "regular_session_completeness": round(completeness, 8),
            "invalid_ohlc_count": invalid, "nonpositive_price_count": nonpositive,
            "future_timestamp_count": future, "partial_candle_count": partial, "status": status,
            "earliest_time_utc": rows[0]["open_time_utc"] if rows else None,
            "latest_time_utc": rows[-1]["open_time_utc"] if rows else None,
        }
        cursor.execute(
            """INSERT app.market_data_quality_runs
               (quality_run_id,market_id,timeframe,earliest_time_utc,latest_time_utc,candle_count,
                duplicate_count,missing_period_count,invalid_ohlc_count,nonpositive_price_count,
                future_timestamp_count,partial_candle_count,status,details_json)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (str(uuid4()), market_id, timeframe, result["earliest_time_utc"], result["latest_time_utc"],
             len(rows), 0, missing, invalid, nonpositive, future, partial, status,
             json.dumps({"calendar_code": str(schedule["calendar_code"]),
                         "session_aware_missing_periods": True,
                         "recent_missing_period_count": recent_missing,
                         "regular_session_observed_count": observed_regular,
                         "regular_session_completeness": round(completeness, 8),
                         "minimum_historical_completeness": 0.985,
                         "features_segmented_at_gaps": True,
                         "provider_boundaries_excluded_from_status": True,
                         "historical_quality_authority": "app.data_quality_segments",
                         "provider_diagnostics": provider_diagnostics})),
        )
        connection.commit()
    return result


def backfill_historical_m5(
    settings: Settings, *, symbols: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY"),
    page_size: int = 500, max_pages_per_market: int = 1,
) -> dict[str, object]:
    """Quota-bounded, resumable backfill. A run can never exceed its declared page budget."""
    if max_pages_per_market < 1 or max_pages_per_market > 10:
        raise ValueError("max_pages_per_market must be between 1 and 10")
    outcomes: dict[str, object] = {}
    with IGDemoClient(settings) as client:
        for symbol in symbols:
            with open_database(settings) as connection:
                cursor = connection.cursor(as_dict=True)
                cursor.execute("SELECT market_id,ig_epic FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
                market = cursor.fetchone()
            if not market:
                outcomes[symbol] = {"status": "UNKNOWN_MARKET"}
                continue
            totals = {"accepted": 0, "rejected": 0}
            try:
                for page in range(1, max_pages_per_market + 1):
                    prices, total_pages = client.historical_prices_page(
                        str(market["ig_epic"]), page_size=page_size, page_number=page,
                    )
                    persisted = _persist_m5(settings, str(market["market_id"]), prices)
                    totals = {name: totals[name] + persisted[name] for name in totals}
                    if page >= total_pages:
                        break
                aggregated = aggregate_m15_history(settings, str(market["market_id"]))
                quality = validate_market_data(settings, str(market["market_id"]), "M5")
                validate_market_data(settings, str(market["market_id"]), "M15")
                outcomes[symbol] = {"status": "COMPLETED", **totals, "m15_aggregated": aggregated,
                                    "quality": quality["status"]}
            except IGDemoUnavailable as exc:
                outcomes[symbol] = {"status": "QUOTA_BLOCKED" if exc.error_code ==
                                    "error.public-api.exceeded-account-historical-data-allowance" else "FAILED",
                                    "error_code": exc.error_code}
                if outcomes[symbol]["status"] == "QUOTA_BLOCKED":
                    break
    return outcomes


def model_readiness(settings: Settings, tenant_id: str) -> dict[str, object]:
    required = settings.model_minimum_rows
    from app.readiness import read_trading_readiness
    platform = read_trading_readiness(settings, tenant_id)
    market_specific_checks = {
        "validated_models", "m5_market_data_current", "m15_aggregation_current",
        "position_sizing_rules",
    }
    platform_ready_without_models = all(
        check["ready"] for name, check in platform["checks"].items()
        if name not in market_specific_checks
    )
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.market_id,m.symbol,m.display_name,
                      COUNT(c.candle_id) raw_rows,MIN(c.open_time_utc) earliest,MAX(c.open_time_utc) latest,
                      (SELECT TOP (1) q.overall_execution_quality FROM app.execution_quality_snapshots q
                       WHERE q.market_id=m.market_id ORDER BY q.evaluated_at_utc DESC) quality_status,
                      (SELECT TOP (1) q.historical_research_quality FROM app.execution_quality_snapshots q
                       WHERE q.market_id=m.market_id ORDER BY q.evaluated_at_utc DESC) historical_quality,
                      (SELECT TOP (1) q.training_quality FROM app.execution_quality_snapshots q
                       WHERE q.market_id=m.market_id ORDER BY q.evaluated_at_utc DESC) training_quality,
                      (SELECT TOP (1) q.cross_provider_continuity FROM app.execution_quality_snapshots q
                       WHERE q.market_id=m.market_id ORDER BY q.evaluated_at_utc DESC) cross_provider_continuity,
                      (SELECT TOP (1) mv.status FROM app.model_versions mv
                       WHERE mv.market_id=m.market_id ORDER BY mv.registered_at_utc DESC) model_status,
                      (SELECT TOP (1) mv.version FROM app.model_versions mv
                       WHERE mv.market_id=m.market_id ORDER BY mv.registered_at_utc DESC) model_version,
                      COALESCE(es.mode,'SHADOW') execution_mode
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
                 AND c.timeframe='M15' AND c.completed=1 AND c.quality_status='PASS'
                 AND c.is_regular_session=1
               LEFT JOIN app.market_execution_states es ON es.market_id=m.market_id AND es.tenant_id=%s
               WHERE m.enabled=1 GROUP BY m.market_id,m.symbol,m.display_name,es.mode ORDER BY m.symbol""",
            (tenant_id,),
        )
        markets = cursor.fetchall()
        result = []
        for row in markets:
            cursor.execute(
                """SELECT
                     MAX(CASE WHEN timeframe='M5' AND completed=1 THEN open_time_utc END) latest_m5,
                     MAX(CASE WHEN timeframe='M15' AND completed=1 THEN open_time_utc END) latest_m15
                   FROM app.candles WHERE market_id=%s""", (str(row["market_id"]),),
            )
            freshness = cursor.fetchone()
            cursor.execute(
                """SELECT COUNT(*) rule_count FROM app.broker_market_rules
                   WHERE market_id=%s AND value_per_price_point_zar IS NOT NULL
                     AND margin_factor_pct IS NOT NULL AND margin_factor_pct>0
                     AND observed_at_utc>=DATEADD(hour,-24,SYSUTCDATETIME())""", (str(row["market_id"]),),
            )
            rule_current = int(cursor.fetchone()["rule_count"] or 0) > 0
            cursor.execute(
                """SELECT TOP (1) executable,decision,blocker_code
                   FROM app.market_decisions WHERE tenant_id=%s AND market_id=%s
                   ORDER BY generated_at_utc DESC""", (tenant_id, str(row["market_id"])),
            )
            combined_decision = cursor.fetchone() or {}
            combined_ready = bool(combined_decision.get("executable"))
            cursor.execute(
                """SELECT TOP (1) me.expectancy,me.profit_factor,me.baseline_outperformed,
                          me.validation_auc,me.result
                   FROM app.model_versions mv LEFT JOIN app.model_evaluations me
                     ON me.model_version_id=mv.model_version_id
                   WHERE mv.market_id=%s ORDER BY mv.registered_at_utc DESC""",
                (str(row["market_id"]),),
            )
            evaluation = cursor.fetchone() or {}
            # The feature pipeline needs 13 leading observations for rolling
            # indicators and four trailing observations for its forward label.
            # Count eligible rows per contiguous segment in SQL instead of
            # rebuilding every market's full feature frame on a status request.
            cursor.execute(
                """WITH ordered AS (
                       SELECT open_time_utc,
                              CASE WHEN DATEDIFF(minute,
                                   LAG(open_time_utc) OVER (ORDER BY open_time_utc),
                                   open_time_utc)=15 THEN 0 ELSE 1 END AS segment_start
                       FROM app.candles
                       WHERE market_id=%s AND timeframe='M15' AND completed=1
                         AND quality_status='PASS' AND is_regular_session=1
                   ), segmented AS (
                       SELECT open_time_utc,
                              SUM(segment_start) OVER (ORDER BY open_time_utc ROWS UNBOUNDED PRECEDING) AS segment_id
                       FROM ordered
                   ), segment_sizes AS (
                       SELECT segment_id,COUNT_BIG(*) AS row_count FROM segmented GROUP BY segment_id
                   )
                   SELECT row_count FROM segment_sizes""", (str(row["market_id"]),),
            )
            feature_rows = sum(feature_complete_rows(int(item["row_count"])) for item in cursor.fetchall())
            cursor.execute(
                """SELECT COUNT(*) governed_count FROM app.model_versions mv
                   JOIN app.holdout_candidates hc ON hc.holdout_candidate_id=mv.holdout_candidate_id
                   WHERE mv.market_id=%s AND mv.status='VALIDATED' AND hc.status='OWNER_APPROVED'
                     AND mv.artifact_sha256=hc.artifact_sha256""", (str(row["market_id"]),),
            )
            validated = int(cursor.fetchone()["governed_count"] or 0) > 0
            now = datetime.now(timezone.utc)
            latest_m5 = freshness["latest_m5"]
            latest_m15 = freshness["latest_m15"]
            m5_fresh = bool(latest_m5) and (now - latest_m5.replace(tzinfo=timezone.utc)).total_seconds() <= settings.execution_m5_fresh_seconds
            m15_fresh = bool(latest_m15) and (now - latest_m15.replace(tzinfo=timezone.utc)).total_seconds() <= settings.execution_m15_fresh_seconds
            quality_pass = row["quality_status"] == "PASS"
            promotion = evaluate_forward_shadow(cursor, tenant_id, str(row["market_id"]))
            forward_shadow_passed = bool(promotion["passed"])
            market_ready = (
                platform_ready_without_models and validated and forward_shadow_passed
                and quality_pass and m5_fresh and m15_fresh and rule_current and combined_ready
                and row["execution_mode"] == "DEMO_AUTO"
            )
            result.append({
                "symbol": row["symbol"], "display_name": row["display_name"],
                "required_rows": required, "raw_m15_rows": int(row["raw_rows"]),
                "feature_complete_rows": feature_rows,
                "progress_pct": round(min(100, feature_rows / required * 100), 1),
                "earliest_candle_utc": row["earliest"].replace(tzinfo=timezone.utc).isoformat() if row["earliest"] else None,
                "latest_candle_utc": row["latest"].replace(tzinfo=timezone.utc).isoformat() if row["latest"] else None,
                "quality_status": row["quality_status"] or "NOT_EVALUATED",
                "historical_research_quality": row["historical_quality"] or "NOT_EVALUATED",
                "training_quality": row["training_quality"] or "NOT_EVALUATED",
                "cross_provider_continuity": row["cross_provider_continuity"] or "NOT_EVALUATED",
                "training_status": "VALIDATED" if validated else "WAITING_FOR_DATA" if feature_rows < required else "REJECTED" if row["model_status"] == "REJECTED" else "READY_TO_TRAIN",
                "model_status": row["model_status"] or "NONE", "model_version": row["model_version"],
                "execution_mode": row["execution_mode"], "demo_auto_ready": market_ready,
                "forward_shadow": promotion,
                "checks": {"sufficient_data": feature_rows >= required, "quality_pass": quality_pass,
                           "positive_expectancy": float(evaluation.get("expectancy") or 0) > 0,
                           "profit_factor": float(evaluation.get("profit_factor") or 0) > 1,
                           "baseline_outperformance": bool(evaluation.get("baseline_outperformed")),
                           "validated_model": validated, "forward_shadow_promoted": forward_shadow_passed,
                           "m5_fresh": m5_fresh, "m15_fresh": m15_fresh,
                           "broker_rule_current": rule_current, "combined_decision_ready": combined_ready,
                           "combined_decision": combined_decision.get("decision") or "NONE",
                           "combined_decision_blocker": combined_decision.get("blocker_code"),
                           "platform_gates": platform_ready_without_models},
                "validation_evidence": {
                    "result": evaluation.get("result"),
                    "auc": str(evaluation.get("validation_auc")) if evaluation.get("validation_auc") is not None else None,
                    "expectancy": str(evaluation.get("expectancy")) if evaluation.get("expectancy") is not None else None,
                    "profit_factor": str(evaluation.get("profit_factor")) if evaluation.get("profit_factor") is not None else None,
                    "baseline_outperformed": bool(evaluation.get("baseline_outperformed")),
                },
            })
    return {"required_feature_rows": required, "markets": result}
