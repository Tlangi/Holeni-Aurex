"""Authenticated one-use owner approval reservation; explicitly no broker submission."""
from __future__ import annotations

import hashlib
import secrets
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import AuthenticatedUser
from app.config import Settings
from app.database import open_database
from app.trade_proposals import _require_owner


ACKNOWLEDGEMENT = "I APPROVE THIS IG DEMO PROPOSAL FOR RISK REVIEW ONLY"


class ApprovalReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    token: str = Field(min_length=32, max_length=128)
    acknowledgement: str

    @field_validator("acknowledgement")
    @classmethod
    def exact_acknowledgement(cls, value: str) -> str:
        if value != ACKNOWLEDGEMENT:
            raise ValueError("Exact risk-review-only acknowledgement required")
        return value


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def issue_approval_challenge(settings: Settings, user: AuthenticatedUser,
                             proposal_id: str) -> dict[str, object]:
    _require_owner(user)
    token = secrets.token_urlsafe(32)
    challenge_id = str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT trade_proposal_id FROM app.trade_proposals WITH (UPDLOCK,HOLDLOCK)
          WHERE trade_proposal_id=%s AND tenant_id=%s AND status='PENDING_OWNER'
            AND expires_at_utc>SYSUTCDATETIME()""", (proposal_id, user.tenant_id))
        if not cursor.fetchone():
            raise ValueError("PROPOSAL_NOT_PENDING_OR_EXPIRED")
        cursor.execute("""INSERT app.proposal_approval_challenges
          (challenge_id,trade_proposal_id,tenant_id,owner_user_id,token_sha256,expires_at_utc)
          SELECT %s,trade_proposal_id,tenant_id,%s,%s,
                 CASE WHEN expires_at_utc<DATEADD(minute,2,SYSUTCDATETIME())
                      THEN expires_at_utc ELSE DATEADD(minute,2,SYSUTCDATETIME()) END
          FROM app.trade_proposals WHERE trade_proposal_id=%s AND tenant_id=%s
            AND status='PENDING_OWNER' AND expires_at_utc>SYSUTCDATETIME()""",
          (challenge_id, user.user_id, _token_digest(token), proposal_id, user.tenant_id))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("PROPOSAL_NOT_PENDING_OR_EXPIRED")
        connection.commit()
    return {"challenge_id": challenge_id, "token": token,
            "purpose": "ONE_USE_RISK_REVIEW_RESERVATION_ONLY",
            "broker_submission_enabled": False}


def reserve_owner_approval(settings: Settings, user: AuthenticatedUser,
                           proposal_id: str, body: ApprovalReservationRequest) -> dict[str, object]:
    _require_owner(user)
    reservation_id = str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        # Lock the proposal first; concurrent approvals serialize on this row.
        cursor.execute("""SELECT trade_proposal_id FROM app.trade_proposals WITH (UPDLOCK,HOLDLOCK)
          WHERE trade_proposal_id=%s AND tenant_id=%s AND status='PENDING_OWNER'
            AND expires_at_utc>SYSUTCDATETIME()""", (proposal_id, user.tenant_id))
        if not cursor.fetchone():
            raise ValueError("PROPOSAL_NOT_PENDING_OR_EXPIRED")
        cursor.execute("""UPDATE app.proposal_approval_challenges SET consumed_at_utc=SYSUTCDATETIME()
          WHERE challenge_id=%s AND trade_proposal_id=%s AND tenant_id=%s AND owner_user_id=%s
            AND token_sha256=%s AND consumed_at_utc IS NULL
            AND expires_at_utc>SYSUTCDATETIME()""",
          (str(body.challenge_id), proposal_id, user.tenant_id, user.user_id, _token_digest(body.token)))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("APPROVAL_TOKEN_INVALID_EXPIRED_OR_USED")
        cursor.execute("""INSERT app.proposal_approval_reservations
          (reservation_id,trade_proposal_id,challenge_id,tenant_id,owner_user_id)
          VALUES(%s,%s,%s,%s,%s)""",
          (reservation_id, proposal_id, str(body.challenge_id), user.tenant_id, user.user_id))
        cursor.execute("""UPDATE app.trade_proposals SET status='OWNER_APPROVED_FOR_RISK',
          decided_by_user_id=%s,decided_at_utc=SYSUTCDATETIME(),
          updated_at_utc=SYSUTCDATETIME()
          WHERE trade_proposal_id=%s AND tenant_id=%s AND status='PENDING_OWNER'
            AND expires_at_utc>SYSUTCDATETIME()""",
          (user.user_id, proposal_id, user.tenant_id))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("PROPOSAL_NOT_PENDING_OR_EXPIRED")
        connection.commit()
    return {"status": "OWNER_APPROVED_FOR_RISK", "reservation_id": reservation_id,
            "trade_proposal_id": proposal_id, "single_use_consumed": True,
            "submission_status": "PRE_SUBMISSION_BLOCKED", "broker_order_submitted": False}
