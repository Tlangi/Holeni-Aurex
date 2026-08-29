from __future__ import annotations

import json
from uuid import uuid4

from pydantic import BaseModel, field_validator

from app.auth import AuthenticatedUser
from app.config import Settings
from app.database import open_database


class EngineControlRequest(BaseModel):
    action: str
    reason: str

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"PAUSE", "RESUME_SHADOW"}:
            raise ValueError("Only PAUSE and RESUME_SHADOW are available")
        return normalized

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5 or len(normalized) > 300:
            raise ValueError("A reason between 5 and 300 characters is required")
        return normalized


class StrategyStatusRequest(BaseModel):
    status: str
    reason: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"ACTIVE", "PAUSED"}:
            raise ValueError("Strategy status must be ACTIVE or PAUSED")
        return normalized

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5 or len(normalized) > 300:
            raise ValueError("A reason between 5 and 300 characters is required")
        return normalized


def _require_owner(user: AuthenticatedUser) -> None:
    if user.role.lower() not in {"owner", "administrator", "admin"}:
        raise PermissionError("Owner role is required")


def change_engine_control(
    settings: Settings, user: AuthenticatedUser, request: EngineControlRequest,
    *, correlation_id: str | None = None,
) -> dict[str, object]:
    _require_owner(user)
    correlation_id = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT mode,new_orders_enabled FROM app.engine_controls WITH (UPDLOCK,HOLDLOCK)
               WHERE tenant_id=%s""",
            (user.tenant_id,),
        )
        control = cursor.fetchone()
        if not control:
            raise ValueError("ENGINE_CONTROL_MISSING")
        from_mode, from_orders = str(control["mode"]), bool(control["new_orders_enabled"])
        to_mode = "PAUSED" if request.action == "PAUSE" else "SHADOW"
        if request.action == "RESUME_SHADOW" and from_mode not in {"PAUSED", "READ_ONLY", "SHADOW"}:
            raise ValueError("DEMO_AUTO_CANNOT_RESUME_AS_SHADOW_WITHOUT_SEPARATE_DEACTIVATION")
        cursor.execute(
            """UPDATE app.engine_controls SET mode=%s,new_orders_enabled=0,pause_reason=%s,
               changed_by_user_id=%s,changed_at_utc=SYSUTCDATETIME() WHERE tenant_id=%s""",
            (to_mode, request.reason if to_mode == "PAUSED" else None, user.user_id, user.tenant_id),
        )
        cursor.execute(
            """INSERT app.engine_control_events
               (tenant_id,from_mode,to_mode,from_new_orders_enabled,to_new_orders_enabled,
                reason,changed_by_user_id,correlation_id)
               VALUES(%s,%s,%s,%s,0,%s,%s,%s)""",
            (user.tenant_id, from_mode, to_mode, from_orders, request.reason, user.user_id, correlation_id),
        )
        cursor.execute(
            """INSERT app.audit_logs
               (tenant_id,user_id,action_code,entity_type,entity_id,correlation_id,metadata_json)
               VALUES(%s,%s,'trading.control.changed','engine_control',%s,%s,%s)""",
            (
                user.tenant_id, user.user_id, user.tenant_id, correlation_id,
                json.dumps({"action": request.action, "from": from_mode, "to": to_mode}, separators=(",", ":")),
            ),
        )
        connection.commit()
    return {"mode": to_mode, "new_orders_enabled": False, "reason": request.reason, "execution_enabled": False}


def read_strategies(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT s.strategy_id,s.strategy_name,s.environment,s.status,sv.version,sv.timeframe,
                      sv.buy_threshold,sv.sell_threshold,sv.features_version,
                      SUM(CASE WHEN mv.status='VALIDATED' THEN 1 ELSE 0 END) validated_models,
                      (SELECT COUNT(*) FROM app.markets WHERE enabled=1) enabled_markets
               FROM app.strategies s
               JOIN app.strategy_versions sv ON sv.strategy_id=s.strategy_id
               LEFT JOIN app.model_versions mv ON mv.strategy_version_id=sv.strategy_version_id
               WHERE s.environment='DEMO' AND s.tenant_id=%s
               GROUP BY s.strategy_id,s.strategy_name,s.environment,s.status,sv.version,sv.timeframe,
                        sv.buy_threshold,sv.sell_threshold,sv.features_version
               ORDER BY s.strategy_name,sv.version DESC""",
            (tenant_id,),
        )
        rows = cursor.fetchall()
    return {"strategies": [
        {"id": str(row["strategy_id"]), "name": str(row["strategy_name"]),
         "environment": str(row["environment"]), "status": str(row["status"]),
         "version": str(row["version"]), "timeframe": str(row["timeframe"]),
         "buy_threshold": str(row["buy_threshold"]), "sell_threshold": str(row["sell_threshold"]),
         "features_version": str(row["features_version"]),
         "validated_models": int(row["validated_models"] or 0),
         "enabled_markets": int(row["enabled_markets"] or 0)} for row in rows]}


def change_strategy_status(
    settings: Settings, user: AuthenticatedUser, strategy_id: str, request: StrategyStatusRequest,
    *, correlation_id: str | None = None,
) -> dict[str, object]:
    _require_owner(user)
    correlation_id = correlation_id or str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT strategy_name,status FROM app.strategies WITH (UPDLOCK,HOLDLOCK)
               WHERE strategy_id=%s AND tenant_id=%s AND environment='DEMO'""",
            (strategy_id, user.tenant_id),
        )
        strategy = cursor.fetchone()
        if not strategy:
            raise LookupError("Strategy not found")
        cursor.execute("UPDATE app.strategies SET status=%s WHERE strategy_id=%s", (request.status, strategy_id))
        cursor.execute(
            """INSERT app.audit_logs
               (tenant_id,user_id,action_code,entity_type,entity_id,correlation_id,metadata_json)
               VALUES(%s,%s,'strategy.status.changed','strategy',%s,%s,%s)""",
            (user.tenant_id, user.user_id, strategy_id, correlation_id,
             json.dumps({"from": strategy["status"], "to": request.status, "reason": request.reason}, separators=(",", ":"))),
        )
        connection.commit()
    return {"id": strategy_id, "name": strategy["strategy_name"], "status": request.status}
