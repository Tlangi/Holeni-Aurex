from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

import pandas as pd

from app.config import Settings
from app.database import open_database
from app.model_pipeline import _market_frame
from app.research_protocol import (
    AUDIT_VERSION,
    PROTOCOL_VERSION,
    TARGET_CATALOG,
    build_selective_target,
    leakage_boundary_audit,
    validate_lifecycle_transition,
)


def _dataset_digest(frame: pd.DataFrame) -> str:
    columns = [name for name in (
        "open", "high", "low", "close", "tick_volume", "observed_spread_bps", "provider",
    ) if name in frame.columns]
    canonical = frame[columns].copy().sort_index()
    canonical.index = canonical.index.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return hashlib.sha256(canonical.to_csv(index=True, float_format="%.12g").encode()).hexdigest()


def _utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def sync_target_specifications(settings: Settings) -> list[dict[str, object]]:
    outcomes = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        for symbol, specifications in TARGET_CATALOG.items():
            cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
            market = cursor.fetchone()
            if not market:
                outcomes.append({"symbol": symbol, "status": "MARKET_UNAVAILABLE"})
                continue
            for specification in specifications:
                configuration = json.dumps(specification.configuration(), sort_keys=True)
                cursor.execute(
                    """SELECT research_target_spec_id FROM app.research_target_specs
                       WHERE market_id=%s AND target_sha256=%s""",
                    (str(market["market_id"]), specification.digest),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """UPDATE app.research_target_specs SET active=1,configuration_json=%s
                           WHERE research_target_spec_id=%s""",
                        (configuration, str(existing["research_target_spec_id"])),
                    )
                    target_id, status = str(existing["research_target_spec_id"]), "CURRENT"
                else:
                    target_id, status = str(uuid4()), "REGISTERED"
                    cursor.execute(
                        """INSERT app.research_target_specs
                             (research_target_spec_id,market_id,protocol_version,target_version,
                              target_sha256,horizon_bars,target_mode,configuration_json,active)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                        (target_id, str(market["market_id"]), PROTOCOL_VERSION, specification.version,
                         specification.digest, specification.horizon_bars, specification.mode, configuration),
                    )
                outcomes.append({"symbol": symbol, "target_spec_id": target_id,
                                 "horizon_bars": specification.horizon_bars,
                                 "mode": specification.mode, "status": status})
        connection.commit()
    return outcomes


def _audit_windows(featured: pd.DataFrame, horizon: int, count: int = 3) -> list[dict[str, object]]:
    if len(featured) < 1000:
        return []
    initial = int(len(featured) * 0.60)
    size = (len(featured) - initial) // count
    windows = []
    for number in range(count):
        start = initial + number * size
        end = len(featured) if number == count - 1 else start + size
        training_end_index = start - horizon - 1
        if training_end_index < 0 or end <= start:
            continue
        windows.append({
            "window_number": number + 1,
            "training_end": featured.index[training_end_index].to_pydatetime(),
            "validation_start": featured.index[start].to_pydatetime(),
            "validation_end": featured.index[end - 1].to_pydatetime(),
        })
    return windows


def run_protocol_boundary_audits(settings: Settings, tenant_id: str) -> list[dict[str, object]]:
    sync_target_specifications(settings)
    outcomes = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
        for market in markets:
            market_id, symbol = str(market["market_id"]), str(market["symbol"])
            frame = _market_frame(cursor, market_id)
            cursor.execute(
                """SELECT TOP (1) research_lineage_id,development_start_utc,
                          development_end_utc,holdout_start_utc
                   FROM app.research_lineages WHERE tenant_id=%s AND market_id=%s
                     AND status IN ('RESERVED','CANDIDATE_FROZEN','HOLDOUT_CONSUMED',
                                    'OWNER_REVIEW_REQUIRED','OWNER_APPROVED')
                   ORDER BY created_at_utc DESC""", (tenant_id, market_id),
            )
            lineage = cursor.fetchone()
            holdout_start = None
            if lineage:
                start = _utc_timestamp(lineage["development_start_utc"])
                end = _utc_timestamp(lineage["development_end_utc"])
                holdout_start = _utc_timestamp(lineage["holdout_start_utc"]).to_pydatetime()
                frame = frame.loc[(frame.index >= start) & (frame.index <= end)].copy()
            if frame.empty:
                outcomes.append({"symbol": symbol, "status": "NO_DEVELOPMENT_DATA"})
                continue
            for specification in TARGET_CATALOG[symbol]:
                cursor.execute(
                    """SELECT research_target_spec_id FROM app.research_target_specs
                       WHERE market_id=%s AND target_sha256=%s""", (market_id, specification.digest),
                )
                target_id = str(cursor.fetchone()["research_target_spec_id"])
                featured = build_selective_target(
                    frame, specification, configured_cost_bps=settings.model_round_trip_cost_bps,
                )
                windows = _audit_windows(featured, specification.horizon_bars)
                audit = leakage_boundary_audit(
                    frame, featured, specification=specification,
                    windows=windows, holdout_start=holdout_start,
                )
                details = {**audit, "windows": windows,
                           "research_lineage_id": str(lineage["research_lineage_id"]) if lineage else None,
                           "holdout_reserved": bool(lineage), "execution_enabled": False}
                cursor.execute(
                    """INSERT app.dataset_boundary_audits
                         (dataset_boundary_audit_id,tenant_id,market_id,research_lineage_id,
                          research_target_spec_id,audit_version,source_start_utc,source_end_utc,
                          source_rows,feature_rows,dataset_sha256,passed,gates_json,details_json)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (str(uuid4()), tenant_id, market_id,
                     str(lineage["research_lineage_id"]) if lineage else None,
                     target_id, AUDIT_VERSION, frame.index.min().to_pydatetime(),
                     frame.index.max().to_pydatetime(), len(frame), len(featured),
                     _dataset_digest(frame), int(bool(audit["passed"])),
                     json.dumps(audit["gates"]), json.dumps(details, default=str)),
                )
                outcomes.append({"symbol": symbol, "horizon_bars": specification.horizon_bars,
                                 "mode": specification.mode, "status": "PASS" if audit["passed"] else "FAIL",
                                 "feature_rows": len(featured), "gates": audit["gates"]})
        connection.commit()
    return outcomes


def read_protocol_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """WITH latest AS (
                   SELECT a.*,ROW_NUMBER() OVER(PARTITION BY a.market_id,a.research_target_spec_id
                                                ORDER BY a.evaluated_at_utc DESC) rn
                   FROM app.dataset_boundary_audits a WHERE a.tenant_id=%s
               )
               SELECT m.symbol,s.target_mode,s.horizon_bars,s.target_version,s.target_sha256,
                      a.passed,a.source_rows,a.feature_rows,a.gates_json,a.evaluated_at_utc
               FROM app.research_target_specs s JOIN app.markets m ON m.market_id=s.market_id
               LEFT JOIN latest a ON a.research_target_spec_id=s.research_target_spec_id AND a.rn=1
               WHERE s.active=1 ORDER BY m.symbol,s.horizon_bars""", (tenant_id,),
        )
        specifications = []
        for row in cursor.fetchall():
            item = {key: (value.isoformat() if isinstance(value, datetime) else value)
                    for key, value in row.items() if key != "gates_json"}
            item["gates"] = json.loads(row["gates_json"]) if row.get("gates_json") else None
            specifications.append(item)
        cursor.execute(
            """SELECT TOP (100) e.candidate_lifecycle_event_id,m.symbol,e.from_state,e.to_state,
                      e.transition_reason,e.evidence_sha256,e.changed_at_utc
               FROM app.candidate_lifecycle_events e JOIN app.markets m ON m.market_id=e.market_id
               WHERE e.tenant_id=%s ORDER BY e.changed_at_utc DESC""", (tenant_id,),
        )
        lifecycle = [{key: (value.isoformat() if isinstance(value, datetime) else value)
                      for key, value in row.items()} for row in cursor.fetchall()]
        cursor.execute(
            """SELECT l.research_lineage_id,m.symbol,l.hypothesis,l.model_families_json,
                      l.status,l.development_start_utc,l.development_end_utc,l.holdout_start_utc,
                      l.holdout_end_utc,l.created_at_utc,s.target_mode,s.horizon_bars,s.target_sha256
               FROM app.research_lineages l JOIN app.markets m ON m.market_id=l.market_id
               LEFT JOIN app.research_target_specs s
                 ON s.research_target_spec_id=l.research_target_spec_id
               WHERE l.tenant_id=%s ORDER BY l.created_at_utc DESC""", (tenant_id,),
        )
        lineages = []
        for row in cursor.fetchall():
            item = {key: (value.isoformat() if isinstance(value, datetime) else value)
                    for key, value in row.items() if key != "model_families_json"}
            item["model_families"] = json.loads(row["model_families_json"])
            lineages.append(item)
    return {"protocol_version": PROTOCOL_VERSION, "target_specifications": specifications,
            "lifecycle_events": lifecycle, "lineages": lineages, "execution_enabled": False,
            "holdout_policy": "UNTOUCHED_UNTIL_EXPLICIT_SINGLE_USE_REVIEW"}


def record_lifecycle_transition(
    settings: Settings, *, tenant_id: str, market_id: str, from_state: str, to_state: str,
    reason: str, evidence: dict[str, object], research_lineage_id: str | None = None,
    holdout_candidate_id: str | None = None, model_version_id: str | None = None,
    changed_by_user_id: str | None = None,
) -> str:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        event_id = insert_lifecycle_event(
            cursor, tenant_id=tenant_id, market_id=market_id, from_state=from_state,
            to_state=to_state, reason=reason, evidence=evidence,
            research_lineage_id=research_lineage_id, holdout_candidate_id=holdout_candidate_id,
            model_version_id=model_version_id, changed_by_user_id=changed_by_user_id,
        )
        connection.commit()
    return event_id


def insert_lifecycle_event(
    cursor: object, *, tenant_id: str, market_id: str, from_state: str, to_state: str,
    reason: str, evidence: dict[str, object], research_lineage_id: str | None = None,
    holdout_candidate_id: str | None = None, model_version_id: str | None = None,
    changed_by_user_id: str | None = None,
) -> str:
    validate_lifecycle_transition(from_state, to_state)
    if not any((research_lineage_id, holdout_candidate_id, model_version_id)):
        raise ValueError("A governed candidate entity is required")
    payload = json.dumps(evidence, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    event_id = str(uuid4())
    cursor.execute(
        """INSERT app.candidate_lifecycle_events
             (candidate_lifecycle_event_id,tenant_id,market_id,research_lineage_id,
              holdout_candidate_id,model_version_id,from_state,to_state,transition_reason,
              evidence_sha256,evidence_json,changed_by_user_id)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (event_id, tenant_id, market_id, research_lineage_id, holdout_candidate_id,
         model_version_id, from_state, to_state, reason, digest, payload, changed_by_user_id),
    )
    return event_id
