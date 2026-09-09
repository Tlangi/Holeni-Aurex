from __future__ import annotations

"""Owner-reviewed trade proposals. Approval never submits a broker order."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth import AuthenticatedUser
from app.config import Settings
from app.database import open_database
from app.email_delivery import send_email
from app.tradingagents_adapter import reject_secrets


OWNER_ROLES = frozenset({"owner", "administrator", "admin"})


class TradeProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    market: str = Field(pattern=r"^[A-Z0-9]{6,12}$")
    trading_agent_run_id: UUID | None = None
    model_version_id: UUID
    direction: Literal["BUY", "SELL"]
    confidence: Decimal = Field(ge=0, le=1)
    proposed_size: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    target_price: Decimal = Field(gt=0)
    risk_zar: Decimal = Field(gt=0)
    horizon_minutes: int = Field(ge=1, le=10080)
    decision_time_utc: datetime
    data_cutoff_utc: datetime
    expires_at_utc: datetime
    rationale_summary: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, object]
    input_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def safety_checks(self) -> "TradeProposalCreate":
        values = (self.decision_time_utc, self.data_cutoff_utc, self.expires_at_utc)
        if any(value.tzinfo is None for value in values):
            raise ValueError("timestamps must be timezone-aware")
        if self.data_cutoff_utc > self.decision_time_utc or self.expires_at_utc <= self.decision_time_utc:
            raise ValueError("invalid proposal time boundary")
        valid_levels = (
            self.direction == "BUY" and self.stop_price < self.entry_price < self.target_price
        ) or (
            self.direction == "SELL" and self.target_price < self.entry_price < self.stop_price
        )
        if not valid_levels:
            raise ValueError("invalid protective stop/target geometry")
        reject_secrets(self.evidence)
        return self


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["APPROVE", "DECLINE"]
    acknowledgement: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def exact_acknowledgement(self) -> "ProposalDecision":
        expected = f"I {self.decision} THIS TRADE PROPOSAL FOR AUREX RISK REVIEW"
        if self.acknowledgement != expected:
            raise ValueError("exact owner acknowledgement is required")
        return self


def _require_owner(user: AuthenticatedUser) -> None:
    if user.role.lower() not in OWNER_ROLES:
        raise PermissionError("OWNER_ROLE_REQUIRED")


def _digest(body: TradeProposalCreate) -> str:
    payload = body.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_trade_proposal(settings: Settings, tenant_id: str, body: TradeProposalCreate) -> str:
    """Internal research entry point; it has no execution imports or authority."""
    proposal_id, digest = str(uuid4()), _digest(body)
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT app.trade_proposals(
             trade_proposal_id,tenant_id,market_id,trading_agent_run_id,model_version_id,direction,
             confidence,proposed_size,entry_price,stop_price,target_price,risk_zar,horizon_minutes,
             decision_time_utc,data_cutoff_utc,expires_at_utc,status,rationale_summary,evidence_json,
             input_snapshot_sha256,proposal_sha256)
             SELECT %s,%s,m.market_id,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_OWNER',%s,%s,%s,%s
             FROM app.markets m WHERE m.symbol=%s AND m.research_enabled=1
             AND EXISTS(SELECT 1 FROM app.model_versions v WHERE v.model_version_id=%s
                  AND v.market_id=m.market_id AND v.status IN ('OWNER_APPROVED','VALIDATED'))
             AND (%s IS NULL OR EXISTS(SELECT 1 FROM app.trading_agent_runs r WHERE r.run_id=%s
                  AND r.market_id=m.market_id AND r.status='SUCCEEDED' AND r.data_cutoff_utc<=%s))""",
            (proposal_id, tenant_id, str(body.trading_agent_run_id) if body.trading_agent_run_id else None,
             str(body.model_version_id), body.direction, body.confidence, body.proposed_size,
             body.entry_price, body.stop_price, body.target_price, body.risk_zar, body.horizon_minutes,
             body.decision_time_utc.astimezone(timezone.utc), body.data_cutoff_utc.astimezone(timezone.utc),
             body.expires_at_utc.astimezone(timezone.utc), body.rationale_summary,
             json.dumps(body.evidence, sort_keys=True), body.input_snapshot_sha256, digest, body.market,
             str(body.model_version_id), str(body.trading_agent_run_id) if body.trading_agent_run_id else None,
             str(body.trading_agent_run_id) if body.trading_agent_run_id else None,
             body.data_cutoff_utc.astimezone(timezone.utc)))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("PROPOSAL_PROVENANCE_NOT_ELIGIBLE")
        connection.commit()
    return proposal_id


def notify_trade_proposal(settings: Settings, tenant_id: str, proposal_id: str) -> None:
    recipient = settings.trade_report_recipient or settings.owner_email or settings.smtp_from_email
    status, error = "NOT_CONFIGURED", None
    if settings.smtp_configured and recipient:
        try:
            send_email(
                settings, recipient=recipient, subject="Aurex trade proposal awaiting review",
                plain_text="A new Aurex research proposal is awaiting review. Sign in to Holeni Aurex "
                           "and open Trading activity > Trade proposals. This email cannot approve or submit a trade.",
            )
            status = "SENT"
        except Exception:
            status, error = "FAILED", "SMTP_DELIVERY_FAILED"
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("""UPDATE app.trade_proposals SET notification_status=%s,
            notification_error_code=%s,updated_at_utc=SYSUTCDATETIME()
            WHERE tenant_id=%s AND trade_proposal_id=%s AND status='PENDING_OWNER'""",
                       (status, error, tenant_id, proposal_id))
        connection.commit()


def read_trade_proposals(settings: Settings, tenant_id: str, limit: int = 50) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""UPDATE app.trade_proposals SET status='EXPIRED',updated_at_utc=SYSUTCDATETIME()
            WHERE tenant_id=%s AND status='PENDING_OWNER' AND expires_at_utc<=SYSUTCDATETIME()""", (tenant_id,))
        cursor.execute("""SELECT TOP (%s) p.trade_proposal_id,m.symbol market,p.direction,p.confidence,
            p.proposed_size,p.entry_price,p.stop_price,p.target_price,p.risk_zar,p.horizon_minutes,
            p.decision_time_utc,p.data_cutoff_utc,p.expires_at_utc,p.status,p.rationale_summary,
            p.notification_status,p.decided_at_utc,p.decision_reason,p.created_at_utc
            FROM app.trade_proposals p JOIN app.markets m ON m.market_id=p.market_id
            WHERE p.tenant_id=%s ORDER BY CASE WHEN p.status='PENDING_OWNER' THEN 0 ELSE 1 END,p.created_at_utc DESC""",
                       (min(max(limit, 1), 100), tenant_id))
        proposals = cursor.fetchall()
        connection.commit()
    return {"status": "OWNER_REVIEW", "execution_authority": "NONE_UNTIL_SEPARATE_GOVERNED_SUBMISSION",
            "count": len(proposals), "proposals": proposals}


def decide_trade_proposal(settings: Settings, user: AuthenticatedUser, proposal_id: str,
                          body: ProposalDecision) -> dict[str, object]:
    _require_owner(user)
    next_status = "OWNER_APPROVED_FOR_RISK" if body.decision == "APPROVE" else "OWNER_DECLINED"
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("""UPDATE app.trade_proposals SET status=%s,decided_by_user_id=%s,
            decided_at_utc=SYSUTCDATETIME(),decision_reason=%s,updated_at_utc=SYSUTCDATETIME()
            WHERE trade_proposal_id=%s AND tenant_id=%s AND status='PENDING_OWNER'
              AND expires_at_utc>SYSUTCDATETIME()""",
                       (next_status, user.user_id, body.reason or None, proposal_id, user.tenant_id))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("PROPOSAL_NOT_PENDING_OR_EXPIRED")
        connection.commit()
    return {"status": next_status, "trade_proposal_id": proposal_id,
            "broker_order_submitted": False,
            "next_step": "DETERMINISTIC_RISK_REVIEW" if body.decision == "APPROVE" else "NONE"}
