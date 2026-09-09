from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.trade_proposals import ProposalDecision, TradeProposalCreate


def valid_proposal(**changes: object) -> dict[str, object]:
    now = datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
    value: dict[str, object] = {
        "market": "USDJPY", "model_version_id": uuid4(), "direction": "BUY",
        "confidence": Decimal("0.61"), "proposed_size": Decimal("0.5"),
        "entry_price": Decimal("147.25"), "stop_price": Decimal("147.05"),
        "target_price": Decimal("147.55"), "risk_zar": Decimal("25"),
        "horizon_minutes": 60, "decision_time_utc": now,
        "data_cutoff_utc": now - timedelta(minutes=1),
        "expires_at_utc": now + timedelta(minutes=15),
        "rationale_summary": "Qualified model signal with local research agreement.",
        "evidence": {"model_gate": "PASS", "risk_authority": "AUREX"},
        "input_snapshot_sha256": "a" * 64,
    }
    value.update(changes)
    return value


def test_proposal_requires_protective_levels() -> None:
    TradeProposalCreate.model_validate(valid_proposal())
    with pytest.raises(ValidationError, match="protective stop"):
        TradeProposalCreate.model_validate(valid_proposal(stop_price=Decimal("147.40")))


def test_approval_is_only_for_risk_review() -> None:
    body = ProposalDecision(decision="APPROVE",
        acknowledgement="I APPROVE THIS TRADE PROPOSAL FOR AUREX RISK REVIEW")
    assert body.decision == "APPROVE"
    assert not hasattr(body, "submit") and not hasattr(body, "broker")


def test_decision_requires_exact_owner_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="exact owner acknowledgement"):
        ProposalDecision(decision="APPROVE", acknowledgement="approve")


def test_proposal_rejects_secret_evidence() -> None:
    with pytest.raises(ValidationError, match="SECRET_MATERIAL_REJECTED"):
        TradeProposalCreate.model_validate(valid_proposal(evidence={"ig_api_key": "FAKE_SECRET"}))
