from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

import joblib
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from app.auth import AuthenticatedUser
from app.config import Settings
from app.database import open_database
from app.readiness import read_trading_readiness
from app.ig_demo import IGDemoClient
from app.ig_execution import (
    ExperimentalCloseGate, ExperimentalExecutionGate, IGDemoExecutionAdapter, IGExecutionBlocked,
    IGExecutionRejected, IGSubmissionUnknown, OrderSubmission,
)
from app.position_sizing import PositionSizingInput, calculate_position_size

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")


ARM_ACKNOWLEDGEMENT = "ARM_EXPERIMENTAL_IG_DEMO_EVIDENCE_PROGRAMME"
KILL_ACKNOWLEDGEMENT = "STOP_EXPERIMENTAL_PROGRAMME"


class ExperimentalDemoBlocked(RuntimeError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class CreateExperimentalProgrammeRequest(BaseModel):
    symbol: str
    model_version_id: str
    starts_at_utc: datetime
    expires_at_utc: datetime
    programme_type: Literal["INFRASTRUCTURE_CANARY", "BROKER_EVIDENCE"] = "INFRASTRUCTURE_CANARY"
    max_attempts: int = Field(default=1, ge=1, le=1000)
    max_holding_minutes: int = Field(default=240, ge=5, le=10080)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.replace("/", "").strip().upper()


class ExperimentalControlRequest(BaseModel):
    action: Literal["ARM", "PAUSE", "RESUME", "KILL", "COMPLETE"]
    acknowledgement: str


class ExperimentalSignalRequest(BaseModel):
    signal_timestamp_utc: datetime
    decision_side: Literal["BUY", "SELL", "HOLD"]
    model_probability: Decimal | None = Field(default=None, ge=0, le=1)
    decision_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    signal_reason: str | None = Field(default=None, max_length=500)
    regime: str | None = Field(default=None, max_length=80)
    market_session: str | None = Field(default=None, max_length=80)
    intended_entry: Decimal | None = Field(default=None, gt=0)
    intended_stop: Decimal | None = Field(default=None, gt=0)
    intended_target: Decimal | None = Field(default=None, gt=0)
    intended_holding_minutes: int | None = Field(default=None, ge=5, le=10080)


class ExperimentalSubmitRequest(BaseModel):
    acknowledgement: Literal["SUBMIT_ONE_EXPERIMENTAL_IG_DEMO_ATTEMPT"]


class ExperimentalReconcileRequest(BaseModel):
    acknowledgement: Literal["RECONCILE_EXPERIMENTAL_IG_DEMO"]


class ExperimentalCloseRequest(BaseModel):
    acknowledgement: Literal["CLOSE_OPEN_EXPERIMENTAL_POSITION"]
    reason: Literal["OWNER_MANUAL_CLOSE", "EMERGENCY_CLOSE", "MAX_HOLDING_PERIOD_EXIT"] = "OWNER_MANUAL_CLOSE"


@dataclass(frozen=True)
class ExperimentalGateInput:
    feature_enabled: bool = False
    owner_armed: bool = False
    within_window: bool = False
    demo_environment_locked: bool = False
    market_tier: int = 3
    owner_active: bool = False
    risk_profile_active: bool = False
    daily_ledger_current: bool = False
    experimental_ledger_current: bool = False
    market_data_fresh: bool = False
    market_open: bool = False
    broker_healthy: bool = False
    broker_rules_current: bool = False
    reconciliation_clear: bool = False
    unknown_submission_count: int = 0
    open_position_count: int = 0
    stop_present: bool = False
    target_present: bool = False
    holding_period_present: bool = False
    daily_loss_limit_reached: bool = False
    programme_drawdown_limit_reached: bool = False
    daily_losing_trade_limit_reached: bool = False
    duplicate_attempt: bool = False
    minimum_size_risk_zar: Decimal = Decimal("0")
    risk_cap_zar: Decimal = Decimal("0")


GATE_CHAIN: tuple[tuple[str, str], ...] = (
    ("feature_enabled", "EXPERIMENTAL_DEMO_FEATURE_DISABLED"),
    ("owner_armed", "EXPERIMENT_NOT_ARMED"),
    ("within_window", "EXPERIMENT_EXPIRED"),
    ("demo_environment_locked", "EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED"),
    ("owner_active", "OWNER_READINESS_FAILED"),
    ("risk_profile_active", "RISK_PROFILE_INACTIVE"),
    ("daily_ledger_current", "DAILY_LEDGER_UNAVAILABLE"),
    ("experimental_ledger_current", "EXPERIMENT_LEDGER_UNAVAILABLE"),
    ("market_data_fresh", "DATA_STALE"),
    ("market_open", "MARKET_CLOSED"),
    ("broker_healthy", "BROKER_ACCOUNT_UNHEALTHY"),
    ("broker_rules_current", "BROKER_RULE_VALIDATION_FAILED"),
    ("reconciliation_clear", "RECONCILIATION_MISMATCH"),
)


def evaluate_experimental_gate(gate: ExperimentalGateInput) -> str:
    """Return the first deterministic blocker or ELIGIBLE.

    Model validation and forward-shadow promotion deliberately do not appear in
    this chain. All operational and risk gates remain fail closed.
    """
    if gate.market_tier == 3:
        return "TIER_RESEARCH_ONLY"
    for attribute, reason in GATE_CHAIN:
        if not bool(getattr(gate, attribute)):
            return reason
    if gate.unknown_submission_count:
        return "UNKNOWN_SUBMISSION_BLOCK"
    if gate.open_position_count >= 1:
        return "OPEN_POSITION_LIMIT"
    if not gate.stop_present:
        return "INVALID_STOP"
    if not gate.target_present:
        return "MISSING_TARGET"
    if not gate.holding_period_present:
        return "MAX_HOLDING_PERIOD_REQUIRED"
    if gate.daily_loss_limit_reached:
        return "EXPERIMENT_DAILY_LOSS_LIMIT"
    if gate.programme_drawdown_limit_reached:
        return "EXPERIMENT_PROGRAMME_DRAWDOWN_LIMIT"
    if gate.daily_losing_trade_limit_reached:
        return "EXPERIMENT_DAILY_LOSING_TRADE_LIMIT"
    if gate.duplicate_attempt:
        return "DUPLICATE_EXPERIMENTAL_ATTEMPT"
    if gate.minimum_size_risk_zar > gate.risk_cap_zar:
        return "SKIP_MINIMUM_SIZE_EXCEEDS_EXPERIMENT_RISK_CAP"
    return "ELIGIBLE"


def experimental_attempt_key(
    programme_id: str, model_artifact_id: str, instrument: str,
    signal_timestamp: datetime, decision_side: str,
) -> str:
    canonical = "|".join((programme_id, model_artifact_id, instrument.upper(),
                           signal_timestamp.astimezone(timezone.utc).isoformat(), decision_side.upper()))
    return sha256(canonical.encode("utf-8")).hexdigest()


def minimum_size_risk_zar(
    *, entry: Decimal, stop: Decimal, minimum_size: Decimal,
    value_per_price_point_zar: Decimal,
) -> Decimal:
    return (abs(entry - stop) * minimum_size * value_per_price_point_zar).quantize(Decimal("0.000001"))


def _artifact_evidence(row: dict[str, object]) -> dict[str, object]:
    path = Path(str(row.get("artifact_path") or ""))
    expected = str(row.get("artifact_sha256") or "")
    evidence: dict[str, object] = {
        "exists": path.is_file(), "checksum_valid": False, "loadable": False,
        "deterministic_inference": False, "feature_version": None, "target_version": None,
    }
    if not path.is_file() or len(expected) != 64:
        return evidence
    evidence["checksum_valid"] = sha256(path.read_bytes()).hexdigest() == expected
    if not evidence["checksum_valid"]:
        return evidence
    try:
        bundle = joblib.load(path)
        model = bundle.get("model") if isinstance(bundle, dict) else None
        features = list(bundle.get("features") or []) if isinstance(bundle, dict) else []
        embedded_feature = bundle.get("feature_version") if isinstance(bundle, dict) else None
        embedded_target = bundle.get("label_version") if isinstance(bundle, dict) else None
        evidence["feature_version"] = embedded_feature or row.get("feature_version")
        evidence["target_version"] = embedded_target or row.get("label_version")
        evidence["metadata_source"] = "ARTIFACT" if embedded_feature and embedded_target else "AUDITED_EXPERIMENT"
        if model is None or not features:
            return evidence
        sample = pd.DataFrame([{feature: 0.0 for feature in features}], columns=features)
        first = model.predict_proba(sample).tolist()
        second = model.predict_proba(sample).tolist()
        evidence["loadable"] = True
        evidence["deterministic_inference"] = first == second
    except Exception:
        return evidence
    return evidence


def _canary_readiness(settings: Settings, tenant_id: str) -> dict[str, object]:
    """Build a direction-neutral, no-order canary projection from persisted IG evidence."""
    lookback_hours = int(getattr(settings, "execution_gap_lookback_hours", 24))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP(1) equity,observed_at_utc FROM app.account_snapshots
               WHERE tenant_id=%s ORDER BY observed_at_utc DESC""", (tenant_id,),
        )
        account = cursor.fetchone() or {}
        cursor.execute(
            """SELECT TOP(1) risk_per_trade_pct,hard_max_risk_per_trade_pct
               FROM app.experimental_risk_policies WHERE tenant_id=%s AND active=1
               ORDER BY version DESC""", (tenant_id,),
        )
        policy = cursor.fetchone() or {}
        cursor.execute(
            """SELECT COUNT(*) unknown_count FROM app.experimental_attempts
               WHERE decision_state IN ('UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH')"""
        )
        unknown = int(cursor.fetchone()["unknown_count"] or 0)
        cursor.execute(
            """SELECT COUNT(*) open_count FROM app.experimental_attempts
               WHERE decision_state='CONFIRMED_OPEN'"""
        )
        open_count = int(cursor.fetchone()["open_count"] or 0)
        cursor.execute(
            """SELECT m.market_id,m.symbol,m.market_tier,m.max_spread_bps,
                      r.min_deal_size,r.size_increment,r.min_stop_distance,
                      r.value_per_price_point_zar,r.market_status,r.current_bid,r.current_ask,
                      r.observed_at_utc rule_observed_at,
                      mv.model_version_id,mv.version model_version,mv.status model_status,
                      mv.artifact_path,mv.artifact_sha256,
                      COALESCE(mv.feature_version,(SELECT TOP(1) e.feature_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC)) feature_version,
                      COALESCE(mv.label_version,(SELECT TOP(1) e.label_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC)) label_version
               FROM app.markets m
               OUTER APPLY (SELECT TOP(1) * FROM app.broker_market_rules x
                            WHERE x.market_id=m.market_id ORDER BY x.observed_at_utc DESC) r
               OUTER APPLY (SELECT TOP(1) * FROM app.model_versions x
                            WHERE x.market_id=m.market_id ORDER BY x.registered_at_utc DESC) mv
               WHERE m.enabled=1 AND m.market_tier=1 ORDER BY m.symbol"""
        )
        rows = cursor.fetchall()
        markets: list[dict[str, object]] = []
        for row in rows:
            market_id = str(row["market_id"])
            cursor.execute(
                """SELECT TOP(15) open_time_utc,high,low,[close] FROM app.candles
                   WHERE market_id=%s AND timeframe='M5' AND completed=1 AND quality_status='PASS'
                   ORDER BY open_time_utc DESC""", (market_id,),
            )
            candles = list(reversed(cursor.fetchall()))
            cursor.execute(
                """SELECT COUNT(*) gap_count FROM app.data_quality_gaps
                   WHERE market_id=%s AND resolved_at_utc IS NULL AND execution_blocking=1
                     AND gap_end_utc>=DATEADD(hour,-%s,SYSUTCDATETIME())""",
                (market_id, lookback_hours),
            )
            gaps = int(cursor.fetchone()["gap_count"] or 0)
            artifact = _artifact_evidence(row)
            bid = Decimal(str(row.get("current_bid") or 0))
            ask = Decimal(str(row.get("current_ask") or 0))
            minimum = Decimal(str(row.get("min_deal_size") or 0))
            point_value = Decimal(str(row.get("value_per_price_point_zar") or 0))
            broker_stop = Decimal(str(row.get("min_stop_distance") or 0))
            ranges: list[Decimal] = []
            previous: Decimal | None = None
            for candle in candles:
                high, low, close = (Decimal(str(candle[name])) for name in ("high", "low", "close"))
                ranges.append(max(high-low, abs(high-previous), abs(low-previous)) if previous else high-low)
                previous = close
            atr = sum(ranges[-14:], Decimal("0")) / Decimal(len(ranges[-14:])) if ranges else Decimal("0")
            stop_distance = max(broker_stop, atr * Decimal("1.5"))
            target_distance = stop_distance * Decimal("2")
            equity = Decimal(str(account.get("equity") or 0))
            risk_zar = (stop_distance * minimum * point_value).quantize(Decimal("0.000001"))
            risk_pct = (risk_zar / equity * Decimal("100")).quantize(Decimal("0.000001")) if equity > 0 else None
            midpoint = (bid + ask) / Decimal("2") if ask > bid > 0 else Decimal("0")
            spread_bps = ((ask-bid) / midpoint * Decimal("10000")).quantize(Decimal("0.000001")) if midpoint else None
            rule_time = row.get("rule_observed_at")
            latest = candles[-1]["open_time_utc"] if candles else None
            metadata_known = bool(artifact.get("feature_version") and artifact.get("target_version"))
            gates = {
                "current_execution_continuity": gaps == 0 and latest is not None,
                "broker_metadata_fresh": bool(rule_time and
                    (datetime.now(timezone.utc).replace(tzinfo=None)-rule_time).total_seconds() <= 24*3600),
                "current_quote": ask > bid > 0,
                "minimum_size_risk": risk_pct is not None and risk_pct <= Decimal("0.25"),
                "stop_target_geometry": stop_distance >= broker_stop > 0 and target_distance > stop_distance,
                "market_tradeable": str(row.get("market_status") or "") == "TRADEABLE",
                "model_artifact": bool(artifact["exists"] and artifact["checksum_valid"] and
                    artifact["loadable"] and artifact["deterministic_inference"] and metadata_known),
                "reconciliation_clear": unknown == 0 and open_count == 0,
            }
            blocker = next((name for name, passed in gates.items() if not passed), None)
            markets.append({
                "symbol": row["symbol"], "model_version_id": row.get("model_version_id"),
                "model_version": row.get("model_version"), "model_status": row.get("model_status"),
                "gates": gates, "blocker": blocker, "eligible_without_global_flag": blocker is None,
                "latest_m5_utc": latest, "unresolved_execution_gaps": gaps,
                "market_status": row.get("market_status"), "bid": bid, "ask": ask,
                "spread_bps": spread_bps, "minimum_size": minimum,
                "minimum_stop_distance": broker_stop, "canary_stop_distance": stop_distance,
                "canary_target_distance": target_distance, "maximum_holding_minutes": 240,
                "minimum_size_risk_zar": risk_zar, "minimum_size_risk_pct": risk_pct,
                "default_risk_pct": policy.get("risk_per_trade_pct"),
                "hard_max_risk_pct": policy.get("hard_max_risk_per_trade_pct"),
                "artifact": artifact,
            })
    eligible = [item for item in markets if item["eligible_without_global_flag"]]
    eligible.sort(key=lambda item: (
        Decimal(str(item["minimum_size_risk_pct"])), Decimal(str(item["spread_bps"])), item["symbol"],
    ))
    return {
        "execution_continuity_lookback_hours": lookback_hours,
        "account_equity_zar": account.get("equity"), "account_observed_at_utc": account.get("observed_at_utc"),
        "unknown_submissions": unknown, "open_experimental_positions": open_count,
        "markets": markets, "recommended": eligible[0] if eligible else None,
        "infrastructure_ready": bool(eligible),
        "global_flag_required_before_owner_arm": True,
        "global_flag_enabled": settings.experimental_demo_enabled,
        "owner_arm_enabled": bool(eligible and settings.experimental_demo_configured),
    }


def _require_owner(user: AuthenticatedUser) -> None:
    if user.role.lower() != "owner":
        raise PermissionError("Only the active tenant owner may control Experimental IG Demo")


def _audit(cursor: object, user: AuthenticatedUser, action: str, entity_id: str,
           correlation_id: str, metadata: dict[str, object]) -> None:
    cursor.execute(
        """INSERT app.audit_logs(tenant_id,user_id,action_code,entity_type,entity_id,
               correlation_id,metadata_json)
           VALUES(%s,%s,%s,'experimental_programme',%s,%s,%s)""",
        (user.tenant_id, user.user_id, action, entity_id, correlation_id,
         json.dumps(metadata, default=str, separators=(",", ":"))),
    )


def _experimental_checks(settings: Settings, tenant_id: str) -> dict[str, object]:
    normal = read_trading_readiness(settings, tenant_id)
    checks = dict(normal.get("checks") or {})
    # These are the only two governance gates Experimental Demo may bypass.
    for market_specific in (
        "validated_models", "demo_execution_opt_in", "m5_market_data_current",
        "m15_aggregation_current", "position_sizing_rules",
    ):
        checks.pop(market_specific, None)
    checks["experimental_feature_flag"] = {
        "ready": settings.experimental_demo_configured,
        "status": "PASS" if settings.experimental_demo_configured else "DEFERRED",
        "detail": "Experimental Demo explicitly enabled" if settings.experimental_demo_configured
                  else "EXPERIMENTAL_DEMO_ENABLED remains false or the Demo environment lock is incomplete",
    }
    blockers = [item["detail"] for item in checks.values()
                if not item.get("ready") and item.get("status") != "DEFERRED"]
    return {
        "status": "READY" if not blockers and settings.experimental_demo_configured else "NOT_READY",
        "checks": checks,
        "blockers": blockers,
        "deferred": [item["detail"] for item in checks.values()
                     if not item.get("ready") and item.get("status") == "DEFERRED"],
    }


def create_experimental_programme(
    settings: Settings, user: AuthenticatedUser, body: CreateExperimentalProgrammeRequest,
    *, correlation_id: str | None = None,
) -> dict[str, object]:
    _require_owner(user)
    starts = body.starts_at_utc.astimezone(timezone.utc)
    expires = body.expires_at_utc.astimezone(timezone.utc)
    if starts >= expires:
        raise ExperimentalDemoBlocked("INVALID_EXPERIMENT_WINDOW")
    programme_id = str(uuid4())
    correlation = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP(1) m.market_id,m.market_tier,m.research_enabled,m.demo_trading_enabled,
                      mv.model_version_id,mv.version,mv.status,mv.artifact_path,mv.artifact_sha256,
                      mv.research_lineage_id,
                      COALESCE(mv.feature_version,(SELECT TOP(1) e.feature_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC)) feature_version,
                      COALESCE(mv.label_version,(SELECT TOP(1) e.label_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC)) label_version
               FROM app.markets m JOIN app.model_versions mv ON mv.market_id=m.market_id
               WHERE m.symbol=%s AND mv.model_version_id=%s""",
            (body.symbol, body.model_version_id),
        )
        row = cursor.fetchone()
        if not row:
            raise ExperimentalDemoBlocked("MODEL_ARTIFACT_NOT_FOUND")
        artifact = _artifact_evidence(row)
        if not (artifact["exists"] and artifact["checksum_valid"] and artifact["loadable"] and
                artifact["deterministic_inference"] and artifact["feature_version"] and
                artifact["target_version"]):
            raise ExperimentalDemoBlocked("MODEL_ARTIFACT_EVIDENCE_INVALID")
        tier = int(row["market_tier"])
        if tier == 3:
            raise ExperimentalDemoBlocked("TIER_RESEARCH_ONLY")
        cursor.execute(
            """SELECT TOP(1) trading_account_id FROM app.trading_accounts
               WHERE tenant_id=%s ORDER BY created_at_utc""", (user.tenant_id,),
        )
        account = cursor.fetchone()
        cursor.execute(
            """SELECT TOP(1) experimental_risk_policy_id FROM app.experimental_risk_policies
               WHERE tenant_id=%s AND active=1""", (user.tenant_id,),
        )
        policy = cursor.fetchone()
        if not account or not policy:
            raise ExperimentalDemoBlocked("EXPERIMENTAL_RISK_POLICY_INACTIVE")
        status = "DRAFT" if bool(row["research_enabled"]) and (
            tier == 1 or bool(row["demo_trading_enabled"])
        ) else "BLOCKED"
        cursor.execute(
            """INSERT app.experimental_programmes(
                 experimental_programme_id,tenant_id,owner_user_id,trading_account_id,market_id,
                 market_tier,model_version_id,model_version,model_status,artifact_path,artifact_sha256,
                 research_lineage_id,feature_version,target_version,experimental_risk_policy_id,
                 programme_type,stage,status,starts_at_utc,expires_at_utc,max_attempts,max_holding_minutes)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CANARY',%s,%s,%s,%s,%s)""",
            (programme_id, user.tenant_id, user.user_id, str(account["trading_account_id"]),
             str(row["market_id"]), tier, str(row["model_version_id"]), row["version"],
             row["status"], row["artifact_path"], row["artifact_sha256"],
             str(row["research_lineage_id"]) if row["research_lineage_id"] else None,
             artifact["feature_version"], artifact["target_version"],
             str(policy["experimental_risk_policy_id"]), body.programme_type, status, starts, expires,
             body.max_attempts, body.max_holding_minutes),
        )
        _audit(cursor, user, "experimental.programme.created", programme_id, correlation,
               {"symbol": body.symbol, "model_version_id": body.model_version_id,
                "model_checksum": row["artifact_sha256"], "status": status,
                "feature_flag": settings.experimental_demo_enabled})
        connection.commit()
    return {"status": status, "experimental_programme_id": programme_id,
            "execution_authority": False, "provenance": "EXPERIMENTAL IG DEMO"}


def control_experimental_programme(
    settings: Settings, user: AuthenticatedUser, programme_id: str,
    body: ExperimentalControlRequest, *, correlation_id: str | None = None,
) -> dict[str, object]:
    _require_owner(user)
    transitions = {
        "PAUSE": ({"ARMED", "RUNNING"}, "PAUSED"),
        "RESUME": ({"PAUSED"}, "ARMED"),
        "KILL": ({"DRAFT", "BLOCKED", "ARMED", "RUNNING", "PAUSED", "LOSS_LIMIT_REACHED"}, "KILLED"),
        "COMPLETE": ({"PAUSED", "RUNNING", "ARMED"}, "COMPLETED"),
    }
    correlation = correlation_id or str(uuid4())
    readiness = _experimental_checks(settings, user.tenant_id)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT p.status,p.expires_at_utc,m.symbol FROM app.experimental_programmes p
               JOIN app.markets m ON m.market_id=p.market_id
               WHERE experimental_programme_id=%s AND tenant_id=%s""", (programme_id, user.tenant_id),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("Experimental programme not found")
        current = str(row["status"])
        if body.action == "ARM":
            if body.acknowledgement != ARM_ACKNOWLEDGEMENT:
                raise ExperimentalDemoBlocked("ARMING_ACKNOWLEDGEMENT_REQUIRED")
            if readiness["status"] != "READY":
                raise ExperimentalDemoBlocked("EXPERIMENTAL_READINESS_FAILED", "; ".join(readiness["blockers"] + readiness["deferred"]))
            canary = _canary_readiness(settings, user.tenant_id)
            market = next((item for item in canary["markets"] if item["symbol"] == row["symbol"]), None)
            if not market or not market["eligible_without_global_flag"]:
                detail = str((market or {}).get("blocker") or "CANARY_MARKET_NOT_READY")
                raise ExperimentalDemoBlocked("CANARY_MARKET_NOT_READY", detail)
            if current not in {"DRAFT", "BLOCKED"}:
                raise ExperimentalDemoBlocked("INVALID_EXPERIMENT_STATE")
            new_status = "ARMED"
            cursor.execute(
                """UPDATE app.experimental_programmes SET status='ARMED',armed_by_user_id=%s,
                       armed_at_utc=SYSUTCDATETIME() WHERE experimental_programme_id=%s""",
                (user.user_id, programme_id),
            )
        else:
            allowed, new_status = transitions[body.action]
            if current not in allowed:
                raise ExperimentalDemoBlocked("INVALID_EXPERIMENT_STATE")
            if body.action == "KILL" and body.acknowledgement != KILL_ACKNOWLEDGEMENT:
                raise ExperimentalDemoBlocked("KILL_ACKNOWLEDGEMENT_REQUIRED")
            completed = ",completed_at_utc=SYSUTCDATETIME()" if new_status in {"KILLED", "COMPLETED"} else ""
            paused = ",paused_at_utc=SYSUTCDATETIME()" if new_status == "PAUSED" else ""
            cursor.execute(
                f"UPDATE app.experimental_programmes SET status=%s{completed}{paused} WHERE experimental_programme_id=%s",
                (new_status, programme_id),
            )
        _audit(cursor, user, f"experimental.programme.{body.action.lower()}", programme_id,
               correlation, {"from": current, "to": new_status})
        connection.commit()
    return {"status": new_status, "experimental_programme_id": programme_id,
            "new_orders_enabled": new_status in {"ARMED", "RUNNING"} and settings.experimental_demo_configured}


def record_experimental_signal(
    settings: Settings, user: AuthenticatedUser, programme_id: str,
    body: ExperimentalSignalRequest, *, correlation_id: str | None = None,
) -> dict[str, object]:
    """Persist signal evidence before any broker submission.

    This endpoint intentionally stops at an eligibility decision. A separately
    reconciled broker worker consumes only ELIGIBLE rows, and the disabled global
    flag ensures deployment cannot submit an order merely by recording a signal.
    """
    _require_owner(user)
    correlation = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT p.status,p.starts_at_utc,p.expires_at_utc,p.market_tier,p.model_version_id,
                      p.max_holding_minutes,m.symbol,erp.risk_per_trade_pct,
                      erp.daily_loss_limit_pct,erp.programme_drawdown_limit_pct,
                      erp.max_daily_losing_trades
               FROM app.experimental_programmes p JOIN app.markets m ON m.market_id=p.market_id
               JOIN app.experimental_risk_policies erp ON erp.experimental_risk_policy_id=p.experimental_risk_policy_id
               WHERE p.experimental_programme_id=%s AND p.tenant_id=%s""",
            (programme_id, user.tenant_id),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("Experimental programme not found")
        key = experimental_attempt_key(programme_id, str(row[4]), row[6],
                                       body.signal_timestamp_utc, body.decision_side)
        cursor.execute("SELECT COUNT(*) FROM app.experimental_attempts WHERE idempotency_key=%s", (key,))
        duplicate = int(cursor.fetchone()[0] or 0) > 0
        now = datetime.now(timezone.utc)
        start = row[1].replace(tzinfo=timezone.utc) if row[1].tzinfo is None else row[1]
        expiry = row[2].replace(tzinfo=timezone.utc) if row[2].tzinfo is None else row[2]
        if duplicate:
            raise ExperimentalDemoBlocked("DUPLICATE_EXPERIMENTAL_ATTEMPT")
        attempt_id = str(uuid4())
        reason = "HOLD_SIGNAL" if body.decision_side == "HOLD" else "PENDING_PRE_SUBMISSION_EVALUATION"
        decision_state = "SKIPPED" if body.decision_side == "HOLD" else "EVALUATED"
        cursor.execute(
            """INSERT app.experimental_attempts(
                 experimental_attempt_id,experimental_programme_id,idempotency_key,signal_timestamp_utc,
                 decision_side,model_probability,decision_threshold,signal_reason,regime,market_session,
                 intended_entry,intended_stop,intended_target,intended_holding_minutes,decision_state,
                 reason_code,correlation_id)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (attempt_id, programme_id, key, body.signal_timestamp_utc, body.decision_side,
             body.model_probability, body.decision_threshold, body.signal_reason, body.regime,
             body.market_session, body.intended_entry, body.intended_stop, body.intended_target,
             body.intended_holding_minutes or int(row[5]), decision_state, reason, correlation),
        )
        _audit(cursor, user, "experimental.attempt.created", attempt_id, correlation,
               {"programme_id": programme_id, "decision": body.decision_side,
                "state": decision_state, "reason_code": reason})
        connection.commit()
    return {"experimental_attempt_id": attempt_id, "decision_state": decision_state,
            "reason_code": reason, "broker_submission": False,
            "provenance": "EXPERIMENTAL IG DEMO"}


def _position_identity(item: dict[str, object]) -> tuple[str, str]:
    position = item.get("position") if isinstance(item.get("position"), dict) else item
    return str(position.get("dealId") or ""), str(position.get("dealReference") or "")


def reconcile_experimental_demo(
    settings: Settings, user: AuthenticatedUser, *, recovery_type: str = "MANUAL",
    correlation_id: str | None = None,
) -> dict[str, object]:
    _require_owner(user)
    correlation = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT a.experimental_attempt_id,a.experimental_programme_id,a.decision_state,
                      a.ig_deal_reference,a.ig_deal_id
               FROM app.experimental_attempts a JOIN app.experimental_programmes p
                 ON p.experimental_programme_id=a.experimental_programme_id
               WHERE p.tenant_id=%s AND a.decision_state IN
                 ('SUBMITTING','SUBMITTED','CONFIRMED_OPEN','UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH')""",
            (user.tenant_id,),
        )
        unresolved = cursor.fetchall()
    if not unresolved:
        return {"status": "CLEAR", "checked": 0, "results": []}

    with IGDemoClient(settings) as client:
        broker_positions = client.positions()
    identities = [_position_identity(item) for item in broker_positions]
    results: list[dict[str, str]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor()
        for attempt in unresolved:
            deal_id = str(attempt["ig_deal_id"] or "")
            reference = str(attempt["ig_deal_reference"] or "")
            matched = any((deal_id and deal_id == candidate_id) or
                          (reference and reference == candidate_ref)
                          for candidate_id, candidate_ref in identities)
            if matched:
                result = "MATCHED"
                state = "CONFIRMED_OPEN"
            elif attempt["decision_state"] == "CONFIRMED_OPEN":
                result = "LOCAL_ONLY"
                state = "RECONCILIATION_MISMATCH"
            else:
                result = "UNKNOWN"
                state = "UNKNOWN_SUBMISSION"
            reconciliation_id = str(uuid4())
            cursor.execute(
                """INSERT app.experimental_reconciliations(
                     experimental_reconciliation_id,experimental_programme_id,
                     experimental_attempt_id,recovery_type,result,local_deal_reference,
                     details_json,correlation_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (reconciliation_id, str(attempt["experimental_programme_id"]),
                 str(attempt["experimental_attempt_id"]), recovery_type, result,
                 reference or None, json.dumps({"broker_position_count": len(identities)}), correlation),
            )
            cursor.execute(
                """UPDATE app.experimental_attempts SET decision_state=%s,
                     reason_code=%s,updated_at_utc=SYSUTCDATETIME()
                   WHERE experimental_attempt_id=%s""",
                (state, None if matched else "RECONCILIATION_MISMATCH" if result == "LOCAL_ONLY"
                 else "UNKNOWN_SUBMISSION_BLOCK", str(attempt["experimental_attempt_id"])),
            )
            _audit(cursor, user, "experimental.reconciliation", reconciliation_id, correlation,
                   {"attempt_id": str(attempt["experimental_attempt_id"]), "result": result,
                    "recovery_type": recovery_type})
            results.append({"attempt_id": str(attempt["experimental_attempt_id"]), "result": result})
        connection.commit()
    clear = all(item["result"] == "MATCHED" for item in results)
    return {"status": "CLEAR" if clear else "BLOCKED", "checked": len(results), "results": results}


def startup_recover_experimental_demo(settings: Settings) -> dict[str, object]:
    """Reconcile active broker evidence on startup before submissions can resume."""
    if not settings.experimental_demo_enabled:
        return {"status": "FEATURE_DISABLED", "checked": 0}
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT TOP(1) u.user_id,u.tenant_id,u.email,u.display_name,u.role
               FROM app.experimental_programmes p JOIN app.users u ON u.user_id=p.owner_user_id
               WHERE p.status IN ('ARMED','RUNNING','PAUSED','LOSS_LIMIT_REACHED')
               ORDER BY p.created_at_utc"""
        )
        row = cursor.fetchone()
    if not row:
        return {"status": "NO_ACTIVE_PROGRAMME", "checked": 0}
    owner = AuthenticatedUser(str(row[0]), str(row[1]), row[2], row[3], row[4])
    return reconcile_experimental_demo(settings, owner, recovery_type="STARTUP")


def submit_experimental_attempt(
    settings: Settings, user: AuthenticatedUser, attempt_id: str,
    *, correlation_id: str | None = None,
) -> dict[str, object]:
    """Submit one reserved attempt once, then confirm and reconcile it immediately."""
    _require_owner(user)
    correlation = correlation_id or str(uuid4())
    readiness = _experimental_checks(settings, user.tenant_id)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT a.*,p.status programme_status,p.starts_at_utc,p.expires_at_utc,
                      p.market_tier,p.max_holding_minutes,p.experimental_risk_policy_id,
                      m.symbol,m.ig_epic,m.max_spread_bps,m.live_trading_enabled,
                      rp.risk_per_trade_pct,rp.daily_loss_limit_pct,
                      rp.programme_drawdown_limit_pct,rp.max_daily_losing_trades,
                      ta.trading_account_id,bc.environment,bc.external_account_id_masked,
                      r.min_deal_size,r.size_increment,r.size_increment_authoritative,
                      r.min_stop_distance,r.value_per_price_point_zar,
                      r.margin_factor_pct,
                      r.deal_currency,r.expiry,r.observed_at_utc rule_observed_at
               FROM app.experimental_attempts a
               JOIN app.experimental_programmes p ON p.experimental_programme_id=a.experimental_programme_id
               JOIN app.markets m ON m.market_id=p.market_id
               JOIN app.experimental_risk_policies rp ON rp.experimental_risk_policy_id=p.experimental_risk_policy_id
               JOIN app.trading_accounts ta ON ta.trading_account_id=p.trading_account_id
               JOIN app.broker_connections bc ON bc.broker_connection_id=ta.broker_connection_id
               JOIN app.broker_market_rules r ON r.market_id=m.market_id AND r.broker_connection_id=bc.broker_connection_id
               WHERE a.experimental_attempt_id=%s AND p.tenant_id=%s""",
            (attempt_id, user.tenant_id),
        )
        item = cursor.fetchone()
        if not item:
            raise LookupError("Experimental attempt not found")
        if item["decision_state"] != "EVALUATED" or int(item["submission_count"]):
            raise ExperimentalDemoBlocked("DUPLICATE_EXPERIMENTAL_ATTEMPT")
        if not bool(item["size_increment_authoritative"]):
            raise ExperimentalDemoBlocked("SIZE_INCREMENT_NOT_AUTHORITATIVE")
        cursor.execute(
            """SELECT COUNT(*) unknown_count FROM app.experimental_attempts
               WHERE decision_state IN ('UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH')"""
        )
        unknown_count = int(cursor.fetchone()["unknown_count"] or 0)
        cursor.execute(
            """SELECT COUNT(*) open_count FROM app.experimental_attempts
               WHERE decision_state='CONFIRMED_OPEN'"""
        )
        open_count = int(cursor.fetchone()["open_count"] or 0)
        cursor.execute(
            """SELECT TOP(1) opening_equity_zar,current_equity_zar,status
               FROM app.daily_risk_ledger WHERE trading_account_id=%s
               ORDER BY ledger_date_sast DESC""", (str(item["trading_account_id"]),),
        )
        base_ledger = cursor.fetchone()
        cursor.execute(
            """SELECT TOP(1) * FROM app.experimental_risk_ledgers
               WHERE experimental_programme_id=%s ORDER BY ledger_date_sast DESC""",
            (str(item["experimental_programme_id"]),),
        )
        experiment_ledger = cursor.fetchone()

    with IGDemoClient(settings) as client:
        account = client.account()
        conversion = client.zar_rate(account.currency)
        details = client.market_details(str(item["ig_epic"]))
        current_positions = client.positions()
        snapshot = details.get("snapshot") or {}
        instrument = details.get("instrument") or {}
        bid = Decimal(str(snapshot.get("bid") or 0))
        ask = Decimal(str(snapshot.get("offer") or 0))
        if bid <= 0 or ask <= bid:
            raise ExperimentalDemoBlocked("STALE_PRICE")
        midpoint = (bid + ask) / Decimal("2")
        market_status = str(snapshot.get("marketStatus") or "UNKNOWN").upper()
        equity_zar = (account.equity * conversion.rate).quantize(Decimal("0.000001"))
        available_zar = (account.available * conversion.rate).quantize(Decimal("0.000001"))
        if not experiment_ledger:
            with open_database(settings) as connection:
                ledger_cursor = connection.cursor()
                ledger_cursor.execute(
                    """INSERT app.experimental_risk_ledgers(
                         experimental_risk_ledger_id,experimental_programme_id,ledger_date_sast,
                         day_start_equity_zar,current_equity_zar,programme_peak_equity_zar,status,
                         reconciled_at_utc)
                       VALUES(%s,%s,CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time'),
                              %s,%s,%s,'CURRENT',SYSUTCDATETIME())""",
                    (str(uuid4()), str(item["experimental_programme_id"]), equity_zar, equity_zar, equity_zar),
                )
                connection.commit()
            ledger_status = "CURRENT"
            ledger_daily_loss = Decimal("0")
            ledger_dd = Decimal("0")
            ledger_losses = 0
        else:
            ledger_status = str(experiment_ledger["status"])
            ledger_daily_loss = max(Decimal("0"), -Decimal(str(experiment_ledger["realized_pnl_zar"])))
            ledger_dd = Decimal(str(experiment_ledger["programme_drawdown_pct"]))
            ledger_losses = int(experiment_ledger["losing_trades"])
        entry = Decimal(str(item["intended_entry"] or midpoint))
        stop = Decimal(str(item["intended_stop"] or 0))
        target = Decimal(str(item["intended_target"] or 0))
        minimum_size = Decimal(str(item["min_deal_size"]))
        point_value = Decimal(str(item["value_per_price_point_zar"] or 0))
        min_risk = minimum_size_risk_zar(entry=entry, stop=stop, minimum_size=minimum_size,
                                         value_per_price_point_zar=point_value) if stop > 0 and point_value > 0 else Decimal("999999999")
        risk_cap = (equity_zar * Decimal(str(item["risk_per_trade_pct"])) / Decimal("100")).quantize(Decimal("0.000001"))
        canonical_sizing = calculate_position_size(PositionSizingInput(
            account_equity=equity_zar,
            risk_percentage=Decimal(str(item["risk_per_trade_pct"])),
            entry_price=entry,
            stop_price=stop,
            broker_minimum_size=minimum_size,
            broker_size_increment=Decimal(str(item["size_increment"] or 0)),
            value_per_point_account_currency=point_value,
            margin_factor_pct=Decimal(str(item["margin_factor_pct"] or 0)),
            available_margin=available_zar,
        ))
        spread_points = ask - bid
        spread_bps = spread_points / midpoint * Decimal("10000")
        now = datetime.now(timezone.utc)
        starts = item["starts_at_utc"].replace(tzinfo=timezone.utc)
        expires = item["expires_at_utc"].replace(tzinfo=timezone.utc)
        checks = readiness["checks"]
        canary = _canary_readiness(settings, user.tenant_id)
        market_readiness = next(
            (candidate for candidate in canary["markets"] if candidate["symbol"] == item["symbol"]), {}
        )
        market_gates = market_readiness.get("gates") or {}
        side = str(item["decision_side"])
        broker_minimum_distance = Decimal(str(item["min_stop_distance"]))
        stop_valid = stop > 0 and abs(entry-stop) >= broker_minimum_distance and (
            (side == "BUY" and stop < entry) or (side == "SELL" and stop > entry)
        )
        target_valid = target > 0 and abs(target-entry) >= broker_minimum_distance and (
            (side == "BUY" and target > entry) or (side == "SELL" and target < entry)
        )
        gate = ExperimentalGateInput(
            feature_enabled=settings.experimental_demo_configured,
            owner_armed=str(item["programme_status"]) in {"ARMED", "RUNNING"},
            within_window=starts <= now < expires,
            demo_environment_locked=str(item["environment"]).lower() == "demo" and
                not bool(item["live_trading_enabled"]),
            market_tier=int(item["market_tier"]),
            owner_active=bool(checks.get("authenticated_owner", {}).get("ready")),
            risk_profile_active=bool(checks.get("active_risk_profile", {}).get("ready")),
            daily_ledger_current=bool(base_ledger and base_ledger["status"] == "CURRENT"),
            experimental_ledger_current=ledger_status == "CURRENT",
            market_data_fresh=bool(market_gates.get("current_execution_continuity")),
            market_open=market_status == "TRADEABLE",
            broker_healthy=bool(checks.get("ig_demo_connected", {}).get("ready")),
            broker_rules_current=bool(market_gates.get("broker_metadata_fresh")),
            reconciliation_clear=bool(checks.get("reconciliation_clear", {}).get("ready")),
            unknown_submission_count=unknown_count,
            open_position_count=max(open_count, len(current_positions)),
            stop_present=stop_valid,
            target_present=target_valid,
            holding_period_present=int(item["intended_holding_minutes"] or item["max_holding_minutes"]) > 0,
            daily_loss_limit_reached=ledger_daily_loss >= equity_zar * Decimal(str(item["daily_loss_limit_pct"])) / Decimal("100"),
            programme_drawdown_limit_reached=ledger_dd >= Decimal(str(item["programme_drawdown_limit_pct"])),
            daily_losing_trade_limit_reached=ledger_losses >= int(item["max_daily_losing_trades"]),
            minimum_size_risk_zar=min_risk, risk_cap_zar=risk_cap,
        )
        reason = evaluate_experimental_gate(gate)
        if reason == "ELIGIBLE" and not canonical_sizing.approved:
            reason = canonical_sizing.rejection_reason or "POSITION_SIZING_REJECTED"
        max_spread = Decimal(str(item["max_spread_bps"] or 0))
        if reason == "ELIGIBLE" and max_spread > 0 and spread_bps > max_spread:
            reason = "SPREAD_TOO_HIGH"

        with open_database(settings) as connection:
            reserve = connection.cursor()
            reserve.execute(
                """UPDATE app.experimental_attempts SET bid=%s,ask=%s,midpoint=%s,
                     spread_points=%s,spread_bps=%s,market_snapshot_at_utc=SYSUTCDATETIME(),
                     market_status=%s,available_margin_zar=%s,account_equity_zar=%s,
                     requested_size=%s,broker_minimum_size=%s,calculated_risk_zar=%s,
                     decision_state=%s,reason_code=%s,
                     submission_count=CASE WHEN %s='ELIGIBLE' THEN 1 ELSE submission_count END,
                     submitted_at_utc=CASE WHEN %s='ELIGIBLE' THEN SYSUTCDATETIME() ELSE submitted_at_utc END,
                     updated_at_utc=SYSUTCDATETIME()
                   WHERE experimental_attempt_id=%s AND submission_count=0""",
                (bid, ask, midpoint, spread_points, spread_bps, market_status, available_zar,
                 equity_zar, minimum_size, minimum_size, min_risk,
                 "SUBMITTING" if reason == "ELIGIBLE" else "SKIPPED", reason,
                 reason, reason, attempt_id),
            )
            if reserve.rowcount != 1:
                raise ExperimentalDemoBlocked("DUPLICATE_EXPERIMENTAL_ATTEMPT")
            _audit(reserve, user, "experimental.attempt.eligibility", attempt_id, correlation,
                   {"reason_code": reason, "minimum_size_risk_zar": str(min_risk),
                    "risk_cap_zar": str(risk_cap), "spread_bps": str(spread_bps)})
            connection.commit()
        if reason != "ELIGIBLE":
            return {"status": "SKIPPED", "reason_code": reason, "broker_submission": False}

        submission = OrderSubmission(
            epic=str(item["ig_epic"]), direction=str(item["decision_side"]), size=minimum_size,
            stop_level=stop, take_profit_level=target, currency_code=str(item["deal_currency"]),
            expiry=str(item["expiry"] or "-"), client_reference=f"AUREX-XP-{attempt_id[:24]}",
        )
        transport_gate = ExperimentalExecutionGate(
            feature_enabled=True, orchestrator_decision="ELIGIBLE", account_id=client.account_id,
            environment="demo", live_trading_enabled=False,
        )
        adapter = IGDemoExecutionAdapter(settings, client)
        try:
            acknowledgement = adapter.submit_experimental(submission, transport_gate)
            confirmation = adapter.confirm(acknowledgement.deal_reference)
        except IGSubmissionUnknown:
            _set_experimental_attempt_state(settings, user, attempt_id, "UNKNOWN_SUBMISSION",
                                            "UNKNOWN_SUBMISSION_BLOCK", correlation)
            raise
        except (IGExecutionBlocked, IGExecutionRejected) as exc:
            rejection = exc.reason if isinstance(exc, IGExecutionRejected) else str(exc)
            _set_experimental_attempt_state(settings, user, attempt_id, "CONFIRMED_REJECTED",
                                            rejection, correlation)
            return {"status": "CONFIRMED_REJECTED", "reason_code": rejection}
        state = "CONFIRMED_OPEN" if confirmation.accepted else "CONFIRMED_REJECTED"
        reason_code = None if confirmation.accepted else confirmation.reason
        with open_database(settings) as connection:
            final = connection.cursor()
            final.execute(
                """UPDATE app.experimental_attempts SET decision_state=%s,reason_code=%s,
                     ig_deal_reference=%s,ig_deal_id=%s,confirmed_at_utc=SYSUTCDATETIME(),
                     updated_at_utc=SYSUTCDATETIME() WHERE experimental_attempt_id=%s""",
                (state, reason_code, acknowledgement.deal_reference, confirmation.deal_id, attempt_id),
            )
            final.execute(
                """INSERT app.experimental_observations(
                     experimental_observation_id,experimental_attempt_id,actual_fill,
                     confirmation_latency_ms,cost_currency,conversion_rate,conversion_source,
                     conversion_at_utc,evidence_json)
                   VALUES(%s,%s,%s,NULL,%s,%s,%s,%s,%s)""",
                (str(uuid4()), attempt_id, confirmation.level, account.currency, conversion.rate,
                 conversion.source, conversion.observed_at_utc,
                 json.dumps({"provenance": "EXPERIMENTAL IG DEMO", "broker_status": confirmation.status,
                             "reason": confirmation.reason})),
            )
            _audit(final, user, "experimental.attempt.confirmed", attempt_id, correlation,
                   {"state": state, "deal_reference_suffix": acknowledgement.deal_reference[-4:]})
            connection.commit()
        if state == "CONFIRMED_REJECTED":
            _complete_resolved_canary(settings, attempt_id)
        return {"status": state, "experimental_attempt_id": attempt_id,
                "deal_id_suffix": confirmation.deal_id[-4:] if confirmation.deal_id else None}


def _set_experimental_attempt_state(
    settings: Settings, user: AuthenticatedUser, attempt_id: str, state: str,
    reason_code: str, correlation_id: str,
) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.experimental_attempts SET decision_state=%s,reason_code=%s,
                 updated_at_utc=SYSUTCDATETIME() WHERE experimental_attempt_id=%s""",
            (state, reason_code[:100], attempt_id),
        )
        _audit(cursor, user, f"experimental.attempt.{state.lower()}", attempt_id,
               correlation_id, {"reason_code": reason_code[:100]})
        connection.commit()
    if state == "CONFIRMED_REJECTED":
        _complete_resolved_canary(settings, attempt_id)


def _complete_resolved_canary(settings: Settings, attempt_id: str) -> None:
    """A one-order canary stops after its first resolved broker submission."""
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE p SET status='COMPLETED',completed_at_utc=SYSUTCDATETIME()
               FROM app.experimental_programmes p JOIN app.experimental_attempts a
                 ON a.experimental_programme_id=p.experimental_programme_id
               WHERE a.experimental_attempt_id=%s AND p.stage='CANARY' AND p.max_attempts=1
                 AND a.submission_count=1
                 AND a.decision_state IN ('CONFIRMED_REJECTED','CONFIRMED_CLOSED')
                 AND p.status IN ('ARMED','RUNNING','PAUSED')""", (attempt_id,),
        )
        connection.commit()


def close_experimental_position(
    settings: Settings, user: AuthenticatedUser, attempt_id: str,
    body: ExperimentalCloseRequest, *, correlation_id: str | None = None,
) -> dict[str, object]:
    """Close one known experimental position once and reconcile the close."""
    _require_owner(user)
    correlation = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT a.experimental_programme_id,a.decision_state,a.decision_side,
                      a.requested_size,a.ig_deal_id,a.ig_deal_reference,m.ig_epic,
                      r.expiry,bc.environment,m.live_trading_enabled
               FROM app.experimental_attempts a JOIN app.experimental_programmes p
                 ON p.experimental_programme_id=a.experimental_programme_id
               JOIN app.markets m ON m.market_id=p.market_id
               JOIN app.trading_accounts ta ON ta.trading_account_id=p.trading_account_id
               JOIN app.broker_connections bc ON bc.broker_connection_id=ta.broker_connection_id
               JOIN app.broker_market_rules r ON r.broker_connection_id=bc.broker_connection_id
                 AND r.market_id=m.market_id
               WHERE a.experimental_attempt_id=%s AND p.tenant_id=%s""",
            (attempt_id, user.tenant_id),
        )
        item = cursor.fetchone()
    if not item:
        raise LookupError("Experimental position not found")
    if item["decision_state"] != "CONFIRMED_OPEN" or not item["ig_deal_id"]:
        raise ExperimentalDemoBlocked("NO_OPEN_EXPERIMENTAL_POSITION")
    with IGDemoClient(settings) as client:
        positions = client.positions()
        matched = next((position for position in positions
                        if _position_identity(position)[0] == str(item["ig_deal_id"])), None)
        if not matched:
            _set_experimental_attempt_state(settings, user, attempt_id,
                                            "RECONCILIATION_MISMATCH",
                                            "RECONCILIATION_MISMATCH", correlation)
            raise ExperimentalDemoBlocked("RECONCILIATION_MISMATCH")
        transport_gate = ExperimentalCloseGate(
            account_id=client.account_id, environment=str(item["environment"]),
            live_trading_enabled=bool(item["live_trading_enabled"]),
        )
        close_direction = "SELL" if str(item["decision_side"]) == "BUY" else "BUY"
        adapter = IGDemoExecutionAdapter(settings, client)
        try:
            acknowledgement = adapter.close_experimental(
                deal_id=str(item["ig_deal_id"]), direction=close_direction,
                size=Decimal(str(item["requested_size"])), epic=str(item["ig_epic"]),
                expiry=str(item["expiry"] or "-"), gate=transport_gate,
            )
            confirmation = adapter.confirm(acknowledgement.deal_reference)
        except IGSubmissionUnknown:
            _set_experimental_attempt_state(settings, user, attempt_id, "UNKNOWN_SUBMISSION",
                                            "UNKNOWN_SUBMISSION_BLOCK", correlation)
            raise
    if not confirmation.accepted:
        raise ExperimentalDemoBlocked("EXPERIMENTAL_CLOSE_REJECTED", confirmation.reason)
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.experimental_attempts SET decision_state='CONFIRMED_CLOSED',
                 reason_code=%s,confirmed_at_utc=SYSUTCDATETIME(),updated_at_utc=SYSUTCDATETIME()
               WHERE experimental_attempt_id=%s""", (body.reason, attempt_id),
        )
        cursor.execute(
            """UPDATE app.experimental_observations SET exit_price=%s,exit_reason=%s,
                 holding_seconds=DATEDIFF(second,observed_at_utc,SYSUTCDATETIME()),
                 observed_at_utc=SYSUTCDATETIME()
               WHERE experimental_attempt_id=%s""",
            (confirmation.level, body.reason, attempt_id),
        )
        reconciliation_id = str(uuid4())
        cursor.execute(
            """INSERT app.experimental_reconciliations(
                 experimental_reconciliation_id,experimental_programme_id,experimental_attempt_id,
                 recovery_type,result,local_deal_reference,broker_deal_reference,details_json,correlation_id)
               VALUES(%s,%s,%s,'CLOSE','CONFIRMED_CLOSED',%s,%s,%s,%s)""",
            (reconciliation_id, str(item["experimental_programme_id"]), attempt_id,
             str(item["ig_deal_reference"]), acknowledgement.deal_reference,
             json.dumps({"exit_reason": body.reason, "deal_id_suffix": str(item["ig_deal_id"])[-4:]}),
             correlation),
        )
        _audit(cursor, user, "experimental.position.closed", attempt_id, correlation,
               {"reason": body.reason, "reconciliation_id": reconciliation_id})
        connection.commit()
    _complete_resolved_canary(settings, attempt_id)
    return {"status": "CONFIRMED_CLOSED", "experimental_attempt_id": attempt_id,
            "exit_reason": body.reason}


def enforce_experimental_max_holding(settings: Settings) -> list[dict[str, object]]:
    """Close due positions once; uncertain close outcomes become the global circuit breaker."""
    if not settings.experimental_demo_configured:
        return []
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT a.experimental_attempt_id,u.user_id,u.tenant_id,u.email,u.display_name,u.role
               FROM app.experimental_attempts a
               JOIN app.experimental_programmes p ON p.experimental_programme_id=a.experimental_programme_id
               JOIN app.users u ON u.user_id=p.owner_user_id
               JOIN app.experimental_observations o ON o.experimental_attempt_id=a.experimental_attempt_id
               WHERE a.decision_state='CONFIRMED_OPEN'
                 AND DATEADD(minute,COALESCE(a.intended_holding_minutes,p.max_holding_minutes),
                             o.observed_at_utc)<=SYSUTCDATETIME()"""
        )
        rows = cursor.fetchall()
    outcomes: list[dict[str, object]] = []
    for row in rows:
        owner = AuthenticatedUser(str(row[1]), str(row[2]), row[3], row[4], row[5])
        try:
            outcomes.append(close_experimental_position(
                settings, owner, str(row[0]),
                ExperimentalCloseRequest(
                    acknowledgement="CLOSE_OPEN_EXPERIMENTAL_POSITION",
                    reason="MAX_HOLDING_PERIOD_EXIT",
                ),
            ))
        except Exception as exc:
            outcomes.append({"experimental_attempt_id": str(row[0]), "status": "BLOCKED",
                             "reason": type(exc).__name__})
    return outcomes


def read_experimental_lab(settings: Settings, user: AuthenticatedUser, limit: int = 100) -> dict[str, object]:
    _require_owner(user)
    readiness = _experimental_checks(settings, user.tenant_id)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT p.experimental_programme_id,m.symbol,p.market_tier,p.model_version,p.model_status,
                      p.artifact_sha256,p.feature_version,p.target_version,p.programme_type,p.stage,p.status,
                      p.starts_at_utc,p.expires_at_utc,p.max_attempts,p.max_holding_minutes,p.armed_at_utc,
                      rp.risk_per_trade_pct,rp.hard_max_risk_per_trade_pct,rp.daily_loss_limit_pct,
                      rp.programme_drawdown_limit_pct,rp.max_daily_losing_trades,rp.max_open_positions,
                      (SELECT COUNT(*) FROM app.experimental_attempts a WHERE a.experimental_programme_id=p.experimental_programme_id) attempt_count,
                      (SELECT COUNT(*) FROM app.experimental_observations o JOIN app.experimental_attempts a ON a.experimental_attempt_id=o.experimental_attempt_id WHERE a.experimental_programme_id=p.experimental_programme_id) observation_count,
                      (SELECT COUNT(*) FROM app.experimental_attempts a WHERE a.experimental_programme_id=p.experimental_programme_id AND a.decision_state IN ('UNKNOWN_SUBMISSION','RECONCILIATION_MISMATCH')) unknown_count
               FROM app.experimental_programmes p JOIN app.markets m ON m.market_id=p.market_id
               JOIN app.experimental_risk_policies rp ON rp.experimental_risk_policy_id=p.experimental_risk_policy_id
               WHERE p.tenant_id=%s ORDER BY p.created_at_utc DESC""", (user.tenant_id,),
        )
        programmes = cursor.fetchall()
        cursor.execute(
            """SELECT TOP(%s) a.experimental_attempt_id,a.experimental_programme_id,a.signal_timestamp_utc,
                      a.decision_side,a.model_probability,a.decision_state,a.reason_code,a.requested_size,
                      a.calculated_risk_zar,a.ig_deal_reference,a.ig_deal_id,a.submitted_at_utc,
                      a.confirmed_at_utc,o.actual_fill,o.spread_zar,o.slippage_zar,o.net_pnl_zar,
                      o.exit_reason,o.holding_seconds
               FROM app.experimental_attempts a JOIN app.experimental_programmes p ON p.experimental_programme_id=a.experimental_programme_id
               LEFT JOIN app.experimental_observations o ON o.experimental_attempt_id=a.experimental_attempt_id
               WHERE p.tenant_id=%s ORDER BY a.created_at_utc DESC""", (limit, user.tenant_id),
        )
        attempts = cursor.fetchall()
        cursor.execute(
            """SELECT symbol,market_tier,research_enabled,demo_trading_enabled,
                      CASE WHEN market_tier=3 THEN 'BLOCKED' WHEN market_tier=2 AND demo_trading_enabled=0 THEN 'PREREQUISITES_REQUIRED' ELSE 'OWNER_ARMING_REQUIRED' END experimental_eligibility
               FROM app.markets WHERE enabled=1 ORDER BY market_tier,symbol"""
        )
        tier_matrix = cursor.fetchall()
        cursor.execute(
            """SELECT mv.model_version_id,m.symbol,m.market_tier,mv.model_name,mv.version,
                      mv.status,mv.artifact_path,mv.artifact_sha256,
                      COALESCE(mv.feature_version,(SELECT TOP(1) e.feature_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC),'UNKNOWN') feature_version,
                      COALESCE(mv.label_version,(SELECT TOP(1) e.label_version
                        FROM app.research_experiments e WHERE e.model_version=mv.version
                        AND e.retrain_type='DIAGNOSTIC_REPLAY' ORDER BY e.completed_at_utc DESC),'UNKNOWN') target_version
               FROM app.model_versions mv JOIN app.markets m ON m.market_id=mv.market_id
               WHERE m.enabled=1 AND m.market_tier IN (1,2)
                 AND mv.status IN ('REJECTED','CANDIDATE','DEVELOPMENT_PASSED','HOLDOUT_PASSED','OWNER_APPROVED','VALIDATED')
               ORDER BY m.market_tier,m.symbol,mv.registered_at_utc DESC"""
        )
        candidates = cursor.fetchall()
    for candidate in candidates:
        evidence = _artifact_evidence(candidate)
        candidate["feature_version"] = evidence.get("feature_version") or candidate["feature_version"]
        candidate["target_version"] = evidence.get("target_version") or candidate["target_version"]
        candidate["artifact_valid"] = bool(evidence["exists"] and evidence["checksum_valid"] and
                                            evidence["loadable"] and evidence["deterministic_inference"])
    canary = _canary_readiness(settings, user.tenant_id)
    return {
        "programme": "BROKER EVIDENCE PROGRAMME",
        "warning": "NOT MODEL APPROVAL — IG DEMO ONLY",
        "global_feature_flag": settings.experimental_demo_enabled,
        "configured": settings.experimental_demo_configured,
        "normal_demo_auto_unchanged": True,
        "readiness": readiness,
        "programmes": programmes,
        "attempts": attempts,
        "tier_matrix": tier_matrix,
        "candidates": candidates,
        "canary_readiness": canary,
        "provenance": "EXPERIMENTAL IG DEMO",
        "promotion_authority": "NONE",
    }
