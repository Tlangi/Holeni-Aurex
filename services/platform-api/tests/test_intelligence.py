from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.intelligence import AgentDecision, Direction, provider_status


def valid_decision(**overrides: object) -> dict[str, object]:
    requested = datetime(2026, 9, 7, 10, tzinfo=timezone.utc)
    values: dict[str, object] = {
        "market": "USDJPY", "requested_analysis_utc": requested, "direction": "LONG",
        "confidence": 0.7, "expected_horizon_minutes": 60, "reasoning_summary": "Audited evidence.",
        "market_snapshot_id": uuid4(), "prompt_version": "forex-v1", "provider": "test",
        "model": "deterministic-fixture", "agent": "TECHNICAL_ANALYST",
        "market_data_cutoff_utc": requested - timedelta(minutes=1),
        "evidence_quality": "POINT_IN_TIME_VERIFIED", "audit_status": "PASS",
    }
    values.update(overrides)
    return values


def test_validated_forex_decision_has_no_execution_contract() -> None:
    decision = AgentDecision.model_validate(valid_decision())
    assert decision.direction is Direction.LONG
    assert not {"order", "size", "broker"}.intersection(AgentDecision.model_fields)


def test_future_data_cutoff_is_rejected() -> None:
    requested = datetime(2026, 9, 7, 10, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="data cutoff"):
        AgentDecision.model_validate(valid_decision(market_data_cutoff_utc=requested + timedelta(seconds=1)))


def test_unverified_directional_output_fails_closed() -> None:
    with pytest.raises(ValidationError, match="fail closed"):
        AgentDecision.model_validate(valid_decision(evidence_quality="RESEARCH_ONLY_UNVERIFIED"))
    assert AgentDecision.model_validate(valid_decision(
        evidence_quality="RESEARCH_ONLY_UNVERIFIED", audit_status="PENDING", direction="REJECT")).direction is Direction.REJECT


def test_malformed_or_unknown_agent_output_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentDecision.model_validate(valid_decision(agent="BROKER_EXECUTOR", extra_instruction="BUY"))


def test_optional_provider_is_degraded_without_secret() -> None:
    status = provider_status(Settings(intelligence_enabled=True, llm_provider="openai", llm_model_fast="x"))
    assert status["state"] == "DEGRADED" and status["configured"] is False
    assert status["credentials_exposed"] is False
