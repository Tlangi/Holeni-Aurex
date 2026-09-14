"""Read-only, holdout-bounded baseline evidence for multi-timeframe research."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pandas as pd

from app.config import Settings
from app.database import open_database
from app.model_governance import FEATURE_VERSION, LABEL_VERSION, source_identity


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def bounded_candles(cursor: object, market_id: str, timeframe: str, *,
                    start_utc: datetime, end_utc: datetime,
                    holdout_start_utc: datetime) -> pd.DataFrame:
    """Select canonical research bars with a SQL-enforced holdout boundary."""
    if timeframe not in {"M1", "M5", "M15"}:
        raise ValueError("Unsupported research timeframe")
    start, end, holdout = map(_utc, (start_utc, end_utc, holdout_start_utc))
    if not start < end < holdout:
        raise ValueError("Development range must end strictly before reserved holdout")
    cursor.execute(
        """;WITH ranked AS (
            SELECT candle_id,open_time_utc,[open],high,low,[close],tick_count,source,
                   bid_close,ask_close,spread_close,
                   ROW_NUMBER() OVER(PARTITION BY open_time_utc ORDER BY
                     CASE WHEN source LIKE 'IG_LIGHTSTREAMER%%' THEN 1
                          WHEN source='IG_DEMO_HISTORICAL' THEN 2
                          WHEN source LIKE 'DUKASCOPY%%' THEN 3 ELSE 9 END,
                     COALESCE(ingested_at_utc,created_at_utc) DESC,candle_id DESC) rn
            FROM app.candles WHERE market_id=%s AND timeframe=%s
              AND completed=1 AND quality_status='PASS' AND is_regular_session=1
              AND open_time_utc >= %s AND open_time_utc <= %s
              AND open_time_utc < %s)
          SELECT candle_id,open_time_utc,[open],high,low,[close],tick_count,source,
                 bid_close,ask_close,spread_close
          FROM ranked WHERE rn=1 ORDER BY open_time_utc""",
        (market_id, timeframe, start, end, holdout),
    )
    columns = ["candle_id", "open_time_utc", "open", "high", "low", "close",
               "tick_count", "source", "bid_close", "ask_close", "spread_close"]
    rows = cursor.fetchall()
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    frame["open_time_utc"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    if frame["open_time_utc"].duplicated().any() or frame["open_time_utc"].max() >= pd.Timestamp(holdout):
        raise ValueError("Canonical selection breached unique/holdout boundary")
    return frame.set_index("open_time_utc")


def baseline_digest(frame: pd.DataFrame) -> str:
    if frame.empty:
        raise ValueError("Cannot freeze an empty baseline")
    canonical = frame.sort_index().copy()
    canonical.index = canonical.index.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return hashlib.sha256(canonical.to_csv(index=True, float_format="%.12g").encode()).hexdigest()


def freeze_existing_baselines(settings: Settings, symbols: tuple[str, ...] = ("GBPUSD", "USDJPY")) -> list[dict[str, object]]:
    """Return reproducible manifest records; never write SQL or model artifacts."""
    results: list[dict[str, object]] = []
    identity = source_identity()
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        for symbol in symbols:
            cursor.execute(
                """SELECT TOP (1) l.research_lineage_id,l.market_id,l.development_start_utc,
                          l.development_end_utc,l.holdout_start_utc,l.holdout_end_utc,
                          l.feature_version,l.label_version,l.cost_model_version,l.status
                   FROM app.research_lineages l JOIN app.markets m ON m.market_id=l.market_id
                   WHERE m.symbol=%s AND l.status='RESERVED'
                   ORDER BY l.created_at_utc DESC""", (symbol,),
            )
            lineage = cursor.fetchone()
            if not lineage:
                results.append({"market": symbol, "status": "NO_RESERVED_LINEAGE"})
                continue
            start, end, holdout = (lineage[key] for key in
                                   ("development_start_utc", "development_end_utc", "holdout_start_utc"))
            frame = bounded_candles(cursor, str(lineage["market_id"]), "M15",
                                    start_utc=start, end_utc=end, holdout_start_utc=holdout)
            if frame.empty:
                results.append({"market": symbol, "status": "NO_DEVELOPMENT_CANDLES",
                                "research_lineage_id": str(lineage["research_lineage_id"])})
                continue
            source_counts = frame["source"].astype(str).value_counts().to_dict()
            results.append({
                "market": symbol, "status": "DATASET_SNAPSHOT_READ_ONLY",
                "research_lineage_id": str(lineage["research_lineage_id"]),
                "dataset_sha256": baseline_digest(frame), "dataset_rows": len(frame),
                "dataset_start_utc": frame.index.min().isoformat(),
                "dataset_end_utc": frame.index.max().isoformat(),
                "development_start_utc": _utc(start).isoformat(),
                "development_end_utc": _utc(end).isoformat(),
                "holdout_start_utc": _utc(holdout).isoformat(),
                "holdout_end_utc": _utc(lineage["holdout_end_utc"]).isoformat(),
                "signal_timeframe": "M15", "context_timeframes": [],
                "execution_timeframe": "M1", "feature_version": lineage["feature_version"] or FEATURE_VERSION,
                "label_version": lineage["label_version"] or LABEL_VERSION,
                "cost_model_version": lineage["cost_model_version"],
                "model_family": "NOT_ATTESTED", "thresholds": "NOT_ATTESTED",
                "provider_counts": source_counts, "source_identity": identity,
                "holdout_consumed": False, "model_enabled": False,
            })
    return results
