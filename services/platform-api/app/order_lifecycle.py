from __future__ import annotations

import json
from uuid import uuid4


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"RISK_APPROVED", "REJECTED", "CANCELLED"}),
    "RISK_APPROVED": frozenset({"WOULD_SUBMIT", "SUBMITTING", "REJECTED", "CANCELLED"}),
    "WOULD_SUBMIT": frozenset(),
    "SUBMITTING": frozenset({"SUBMITTED", "SUBMISSION_UNKNOWN", "FAILED"}),
    "SUBMITTED": frozenset({"CONFIRMING", "RECONCILIATION_REQUIRED"}),
    "CONFIRMING": frozenset({"OPEN", "REJECTED", "SUBMISSION_UNKNOWN", "RECONCILIATION_REQUIRED"}),
    "SUBMISSION_UNKNOWN": frozenset({"SUBMITTED", "OPEN", "FAILED", "RECONCILIATION_REQUIRED"}),
    "RECONCILIATION_REQUIRED": frozenset({"SUBMITTED", "OPEN", "FAILED", "CANCELLED"}),
    "OPEN": frozenset({"CLOSED", "RECONCILIATION_REQUIRED"}),
    "REJECTED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
    "CLOSED": frozenset(),
}


def assert_transition(from_status: str, to_status: str) -> None:
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        raise ValueError(f"INVALID_ORDER_TRANSITION:{from_status}->{to_status}")


def transition_intent(
    cursor: object, order_intent_id: str, *, from_status: str, to_status: str,
    event_type: str, correlation_id: str, details: dict[str, object] | None = None,
) -> None:
    assert_transition(from_status, to_status)
    cursor.execute(
        """UPDATE app.order_intents SET status=%s,updated_at_utc=SYSUTCDATETIME()
           WHERE order_intent_id=%s AND status=%s""",
        (to_status, order_intent_id, from_status),
    )
    if cursor.rowcount != 1:
        raise ValueError("ORDER_INTENT_CONCURRENT_TRANSITION")
    cursor.execute(
        """INSERT app.order_intent_events
           (order_intent_id,event_type,from_status,to_status,correlation_id,details_json)
           VALUES(%s,%s,%s,%s,%s,%s)""",
        (
            order_intent_id, event_type, from_status, to_status, correlation_id,
            json.dumps(details, separators=(",", ":"), sort_keys=True) if details else None,
        ),
    )


def record_created_intent(cursor: object, order_intent_id: str, correlation_id: str) -> None:
    cursor.execute(
        """INSERT app.order_intent_events
           (order_intent_id,event_type,from_status,to_status,correlation_id)
           VALUES(%s,'INTENT_CREATED',NULL,'CREATED',%s)""",
        (order_intent_id, correlation_id),
    )
