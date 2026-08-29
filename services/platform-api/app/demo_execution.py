from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator

from app.config import Settings
from app.database import open_database
from app.ig_demo import IGDemoClient
from app.ig_execution import (
    ExecutionGate, IGDemoExecutionAdapter, IGExecutionBlocked, IGExecutionRejected,
    IGSubmissionUnknown, OrderSubmission, assert_execution_gate, validate_order_submission,
)
from app.ig_sync import SyncAlreadyRunning, sync_ig_demo
from app.market_intelligence import model_readiness
from app.order_lifecycle import transition_intent
from app.readiness import read_trading_readiness


class OneOffDemoExecutionRequest(BaseModel):
    order_intent_id: UUID
    acknowledgement: str

    @field_validator("acknowledgement")
    @classmethod
    def explicit_acknowledgement(cls, value: str) -> str:
        if value != "EXECUTE_ONE_OFF_IG_DEMO":
            raise ValueError("Explicit one-off IG Demo acknowledgement is required")
        return value


def execute_one_off_demo(
    settings: Settings, tenant_id: str, user_id: str, request: OneOffDemoExecutionRequest,
    *, correlation_id: str | None = None,
) -> dict[str, object]:
    """Submit one pre-approved intent exactly once; never called by a background worker."""
    if not settings.demo_execution_configured:
        raise IGExecutionBlocked("IG Demo execution opt-in remains disabled")
    correlation_id = correlation_id or str(uuid4())
    readiness = read_trading_readiness(settings, tenant_id)
    markets = model_readiness(settings, tenant_id)["markets"]

    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT oi.order_intent_id,oi.status,oi.created_at_utc,oi.direction,
                      oi.calculated_size,oi.stop_level,oi.take_profit_level,oi.client_reference,
                      oi.trading_account_id,m.market_id,m.symbol,m.ig_epic,
                      s.model_version_id,s.market_decision_id,rd.decision AS risk_decision,
                      r.min_deal_size,r.deal_currency,r.expiry,
                      ec.mode,ec.new_orders_enabled
               FROM app.order_intents oi
               JOIN app.signals s ON s.signal_id=oi.signal_id
               JOIN app.risk_decisions rd ON rd.risk_decision_id=oi.risk_decision_id
               JOIN app.markets m ON m.market_id=oi.market_id
               JOIN app.trading_accounts ta ON ta.trading_account_id=oi.trading_account_id
               JOIN app.broker_connections bc ON bc.broker_connection_id=ta.broker_connection_id
               JOIN app.broker_market_rules r ON r.broker_connection_id=bc.broker_connection_id
                    AND r.market_id=m.market_id
               JOIN app.engine_controls ec ON ec.tenant_id=oi.tenant_id
               WHERE oi.order_intent_id=%s AND oi.tenant_id=%s""",
            (str(request.order_intent_id), tenant_id),
        )
        intent = cursor.fetchone()
        if not intent:
            raise IGExecutionBlocked("Order intent does not exist for this tenant")
        market = next((item for item in markets if item["symbol"] == intent["symbol"]), None)
        if not market or not bool(market["demo_auto_ready"]):
            raise IGExecutionBlocked("The selected market has not passed DEMO_TEST_READY")
        if intent["status"] != "RISK_APPROVED" or intent["risk_decision"] != "APPROVED":
            raise IGExecutionBlocked("A fresh APPROVED risk decision is required")
        age = (datetime.now(timezone.utc) - intent["created_at_utc"].replace(tzinfo=timezone.utc)).total_seconds()
        if age > 300:
            raise IGExecutionBlocked("The risk-approved intent is stale")
        if Decimal(str(intent["calculated_size"])) != Decimal(str(intent["min_deal_size"])):
            raise IGExecutionBlocked("The controlled test must use the broker minimum size")
        if not intent["market_decision_id"]:
            raise IGExecutionBlocked("An audited combined market decision is required")

        global_exclusions = {
            "validated_models", "m5_market_data_current", "m15_aggregation_current",
            "position_sizing_rules",
        }
        global_ready = all(
            check["ready"] for name, check in readiness["checks"].items()
            if name not in global_exclusions
        )
        gate = ExecutionGate(
            readiness_status="READY" if global_ready else "NOT_READY",
            engine_mode=str(intent["mode"]),
            new_orders_enabled=bool(intent["new_orders_enabled"]),
            intent_status=str(intent["status"]),
            account_id=settings.ig_account_id,
            market_readiness_status="READY" if market["demo_auto_ready"] else "NOT_READY",
        )
        submission = OrderSubmission(
            epic=str(intent["ig_epic"]), direction=str(intent["direction"]),
            size=Decimal(str(intent["calculated_size"])),
            stop_level=Decimal(str(intent["stop_level"])),
            take_profit_level=Decimal(str(intent["take_profit_level"])),
            currency_code=str(intent["deal_currency"]), expiry=str(intent["expiry"] or "-"),
            client_reference=str(intent["client_reference"]),
        )
        assert_execution_gate(settings, gate)
        try:
            validate_order_submission(submission)
        except ValueError as exc:
            raise IGExecutionBlocked("The order submission contract is invalid") from exc
        attempt_id = str(uuid4())
        cursor.execute(
            """SELECT demo_execution_attempt_id FROM app.demo_execution_attempts WITH (UPDLOCK,HOLDLOCK)
               WHERE order_intent_id=%s""", (str(request.order_intent_id),),
        )
        if cursor.fetchone():
            raise IGExecutionBlocked("This intent already has a one-off execution attempt")
        cursor.execute(
            """INSERT app.demo_execution_attempts
               (demo_execution_attempt_id,tenant_id,user_id,order_intent_id,market_id,
                model_version_id,market_decision_id,correlation_id,status,submission_count)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'SUBMITTING',1)""",
            (attempt_id, tenant_id, user_id, str(request.order_intent_id),
             str(intent["market_id"]), str(intent["model_version_id"]),
             str(intent["market_decision_id"]), correlation_id),
        )
        transition_intent(
            cursor, str(request.order_intent_id), from_status="RISK_APPROVED", to_status="SUBMITTING",
            event_type="DEMO_ONE_OFF_SUBMISSION_RESERVED", correlation_id=correlation_id,
            details={"attempt_id": attempt_id, "submission_limit": 1},
        )
        connection.commit()  # Persist the one-shot reservation before any network call.

    try:
        with IGDemoClient(settings) as client:
            adapter = IGDemoExecutionAdapter(settings, client)
            acknowledgement = adapter.submit(submission, gate)
        _acknowledge(settings, attempt_id, str(request.order_intent_id), correlation_id,
                     acknowledgement.deal_reference)
    except IGSubmissionUnknown:
        _fail(settings, attempt_id, str(request.order_intent_id), correlation_id,
              "SUBMISSION_UNKNOWN", "SUBMISSION_UNKNOWN")
        raise
    except (IGExecutionRejected, IGExecutionBlocked) as exc:
        code = exc.reason if isinstance(exc, IGExecutionRejected) else "EXECUTION_GATE_BLOCKED"
        _fail(settings, attempt_id, str(request.order_intent_id), correlation_id, "FAILED", code)
        raise

    try:
        _confirming(settings, attempt_id, str(request.order_intent_id), correlation_id)
        with IGDemoClient(settings) as client:
            confirmation = IGDemoExecutionAdapter(settings, client).confirm(acknowledgement.deal_reference)
        if not confirmation.accepted:
            _fail(settings, attempt_id, str(request.order_intent_id), correlation_id,
                  "REJECTED", confirmation.reason, from_status="CONFIRMING")
            return {"status": "REJECTED", "attempt_id": attempt_id, "reason": confirmation.reason}
        try:
            sync_ig_demo(settings, correlation_id=correlation_id)
        except SyncAlreadyRunning:
            _fail(settings, attempt_id, str(request.order_intent_id), correlation_id,
                  "RECONCILIATION_REQUIRED", "SYNC_ALREADY_RUNNING", from_status="CONFIRMING")
            return {"status": "RECONCILIATION_REQUIRED", "attempt_id": attempt_id}
        except Exception as exc:
            _fail(settings, attempt_id, str(request.order_intent_id), correlation_id,
                  "RECONCILIATION_REQUIRED", type(exc).__name__.upper(), from_status="CONFIRMING")
            return {"status": "RECONCILIATION_REQUIRED", "attempt_id": attempt_id}
        return _complete_from_reconciliation(settings, attempt_id, str(request.order_intent_id),
                                             confirmation.deal_id)
    except IGSubmissionUnknown:
        _fail(settings, attempt_id, str(request.order_intent_id), correlation_id,
              "SUBMISSION_UNKNOWN", "CONFIRMATION_UNKNOWN", from_status="CONFIRMING")
        raise


def read_demo_execution_attempts(settings: Settings, tenant_id: str, limit: int = 20) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) a.demo_execution_attempt_id,m.symbol,a.status,a.submission_count,
                      a.failure_code,a.started_at_utc,a.completed_at_utc
               FROM app.demo_execution_attempts a JOIN app.markets m ON m.market_id=a.market_id
               WHERE a.tenant_id=%s ORDER BY a.started_at_utc DESC""",
            (max(1, min(limit, 100)), tenant_id),
        )
        rows = cursor.fetchall()
    return {
        "execution_opt_in": settings.demo_execution_configured,
        "submission_policy": "ONE_ATTEMPT_PER_RISK_APPROVED_INTENT_NO_POST_RETRY",
        "attempts": [
            {"attempt_id": str(row["demo_execution_attempt_id"]), "symbol": row["symbol"],
             "status": row["status"], "submission_count": int(row["submission_count"]),
             "failure_code": row["failure_code"],
             "started_at_utc": row["started_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
             "completed_at_utc": row["completed_at_utc"].replace(tzinfo=timezone.utc).isoformat()
                if row["completed_at_utc"] else None}
            for row in rows
        ],
    }


def _acknowledge(settings: Settings, attempt_id: str, intent_id: str, correlation_id: str, reference: str) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        transition_intent(cursor, intent_id, from_status="SUBMITTING", to_status="SUBMITTED",
                          event_type="IG_DEMO_ACKNOWLEDGED", correlation_id=correlation_id)
        cursor.execute("UPDATE app.order_intents SET broker_deal_reference=%s WHERE order_intent_id=%s",
                       (reference, intent_id))
        cursor.execute("UPDATE app.demo_execution_attempts SET status='ACKNOWLEDGED',deal_reference=%s WHERE demo_execution_attempt_id=%s",
                       (reference, attempt_id))
        connection.commit()


def _confirming(settings: Settings, attempt_id: str, intent_id: str, correlation_id: str) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        transition_intent(cursor, intent_id, from_status="SUBMITTED", to_status="CONFIRMING",
                          event_type="IG_DEMO_CONFIRMATION_STARTED", correlation_id=correlation_id)
        cursor.execute("UPDATE app.demo_execution_attempts SET status='CONFIRMING' WHERE demo_execution_attempt_id=%s",
                       (attempt_id,))
        connection.commit()


def _fail(
    settings: Settings, attempt_id: str, intent_id: str, correlation_id: str,
    status: str, failure_code: str, *, from_status: str = "SUBMITTING",
) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        transition_intent(cursor, intent_id, from_status=from_status, to_status=status,
                          event_type=f"IG_DEMO_{status}", correlation_id=correlation_id,
                          details={"failure_code": failure_code[:100]})
        cursor.execute(
            """UPDATE app.demo_execution_attempts SET status=%s,failure_code=%s,
                      completed_at_utc=SYSUTCDATETIME() WHERE demo_execution_attempt_id=%s""",
            (status, failure_code[:100], attempt_id),
        )
        connection.commit()


def _complete_from_reconciliation(
    settings: Settings, attempt_id: str, intent_id: str, deal_id: str | None,
) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT status FROM app.order_intents WHERE order_intent_id=%s", (intent_id,))
        row = cursor.fetchone()
        final = "OPEN" if row and row["status"] == "OPEN" else "RECONCILIATION_REQUIRED"
        if final != "OPEN" and row and row["status"] == "CONFIRMING":
            transition_intent(cursor, intent_id, from_status="CONFIRMING", to_status=final,
                              event_type="IG_DEMO_RECONCILIATION_REQUIRED", correlation_id=str(uuid4()))
        cursor.execute(
            """UPDATE app.demo_execution_attempts SET status=%s,deal_id=%s,
                      completed_at_utc=SYSUTCDATETIME() WHERE demo_execution_attempt_id=%s""",
            (final, deal_id, attempt_id),
        )
        connection.commit()
    return {"status": final, "attempt_id": attempt_id,
            "deal_id_suffix": deal_id[-4:] if deal_id else None}
