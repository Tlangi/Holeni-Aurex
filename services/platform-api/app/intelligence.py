from __future__ import annotations

"""Fail-closed Forex intelligence contracts; deliberately no broker imports."""

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import Settings

AGENT_ROLES = (
    "TECHNICAL_ANALYST", "MACRO_ANALYST", "NEWS_ANALYST", "MARKET_REGIME_ANALYST",
    "SENTIMENT_ANALYST", "BULL_RESEARCHER", "BEAR_RESEARCHER", "STRATEGY_SYNTHESISER",
    "RISK_REVIEWER", "RESEARCH_MANAGER", "TRADE_REJECTION",
)


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    REJECT = "REJECT"


class EvidenceQuality(StrEnum):
    POINT_IN_TIME_VERIFIED = "POINT_IN_TIME_VERIFIED"
    RESEARCH_ONLY_UNVERIFIED = "RESEARCH_ONLY_UNVERIFIED"
    INSUFFICIENT = "INSUFFICIENT"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    market: str = Field(pattern=r"^[A-Z0-9]{6,12}$")
    requested_analysis_utc: datetime
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    expected_horizon_minutes: int = Field(ge=1, le=1440)
    expected_move_points: float | None = None
    reasoning_summary: str = Field(min_length=1, max_length=2000)
    supporting_factors: list[str] = Field(default_factory=list, max_length=20)
    opposing_factors: list[str] = Field(default_factory=list, max_length=20)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    macro_snapshot_id: UUID | None = None
    market_snapshot_id: UUID
    news_snapshot_id: UUID | None = None
    prompt_version: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=160)
    model_version: str | None = Field(default=None, max_length=160)
    agent: str
    market_data_cutoff_utc: datetime
    macro_data_cutoff_utc: datetime | None = None
    news_data_cutoff_utc: datetime | None = None
    evidence_quality: EvidenceQuality
    audit_status: Literal["PASS", "FAIL", "PENDING"]
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent")
    @classmethod
    def known_agent(cls, value: str) -> str:
        value = value.upper()
        if value not in AGENT_ROLES:
            raise ValueError("unknown Aurex Forex agent role")
        return value

    @model_validator(mode="after")
    def enforce_point_in_time(self) -> "AgentDecision":
        requested = _utc(self.requested_analysis_utc)
        cutoffs = (self.market_data_cutoff_utc, self.macro_data_cutoff_utc, self.news_data_cutoff_utc)
        if any(_utc(value) > requested for value in cutoffs if value is not None):
            raise ValueError("data cutoff cannot be later than requested analysis timestamp")
        verified = self.audit_status == "PASS" and self.evidence_quality == EvidenceQuality.POINT_IN_TIME_VERIFIED
        if not verified and self.direction not in {Direction.NEUTRAL, Direction.REJECT}:
            raise ValueError("unverified evidence must fail closed as NEUTRAL or REJECT")
        return self


def provider_status(settings: Settings) -> dict[str, object]:
    configured = settings.intelligence_provider_configured
    state = "DISABLED" if not settings.intelligence_enabled else "CONFIGURED" if configured else "DEGRADED"
    return {"provider": settings.llm_provider.lower(), "state": state, "configured": configured,
            "mode": "LOCAL_ONLY" if settings.intelligence_local_only else "UNSAFE_NOT_LOCAL_ONLY",
            "fast_model": settings.llm_model_fast or None, "deep_model": settings.llm_model_deep or None,
            "timeout_seconds": settings.llm_timeout_seconds, "max_retries": settings.llm_max_retries,
            "credentials_exposed": False}


def persist_agent_decision(settings: Settings, tenant_id: str, decision: AgentDecision, *,
                           correlation_id: UUID | None = None, latency_ms: int | None = None,
                           input_tokens: int | None = None, output_tokens: int | None = None,
                           estimated_cost_usd: str | None = None) -> str:
    """Persist validated evidence. This is the adapter's sole write capability."""
    from app.database import open_database
    decision_id, run_id = str(uuid4()), str(correlation_id or uuid4())
    payload = decision.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT app.agent_decisions
               (agent_decision_id,tenant_id,correlation_id,market_id,agent_role,direction,confidence,
                expected_horizon_minutes,expected_move_points,reasoning_summary,supporting_factors_json,
                opposing_factors_json,risk_flags_json,macro_snapshot_id,market_snapshot_id,news_snapshot_id,
                provider,model_name,model_version,prompt_version,requested_analysis_utc,market_data_cutoff_utc,
                macro_data_cutoff_utc,news_data_cutoff_utc,latency_ms,input_tokens,output_tokens,
                estimated_cost_usd,evidence_quality,audit_status,provenance_json,provenance_sha256)
               SELECT %s,%s,%s,m.market_id,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               FROM app.markets m WHERE m.symbol=%s AND m.research_enabled=1""",
            (decision_id, tenant_id, run_id, decision.agent, decision.direction.value, decision.confidence,
             decision.expected_horizon_minutes, decision.expected_move_points, decision.reasoning_summary,
             json.dumps(decision.supporting_factors), json.dumps(decision.opposing_factors), json.dumps(decision.risk_flags),
             str(decision.macro_snapshot_id) if decision.macro_snapshot_id else None, str(decision.market_snapshot_id),
             str(decision.news_snapshot_id) if decision.news_snapshot_id else None, decision.provider, decision.model,
             decision.model_version, decision.prompt_version, _utc(decision.requested_analysis_utc),
             _utc(decision.market_data_cutoff_utc), _utc(decision.macro_data_cutoff_utc) if decision.macro_data_cutoff_utc else None,
             _utc(decision.news_data_cutoff_utc) if decision.news_data_cutoff_utc else None, latency_ms, input_tokens,
             output_tokens, estimated_cost_usd, decision.evidence_quality.value, decision.audit_status,
             json.dumps(decision.provenance, sort_keys=True), digest, decision.market))
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("unknown or research-disabled market")
        connection.commit()
    return decision_id


def read_intelligence_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    from app.database import open_database
    decisions: list[dict[str, object]] = []
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            cursor.execute("""SELECT TOP (50) d.agent_decision_id,m.symbol,d.agent_role,d.direction,d.confidence,
                d.provider,d.model_name,d.evidence_quality,d.audit_status,d.requested_analysis_utc,
                d.analysis_timestamp_utc,d.market_data_cutoff_utc FROM app.agent_decisions d
                JOIN app.markets m ON m.market_id=d.market_id WHERE d.tenant_id=%s
                ORDER BY d.analysis_timestamp_utc DESC""", (tenant_id,))
            decisions = cursor.fetchall()
    except Exception:
        decisions = []
    ta_state = ("DISABLED" if not settings.tradingagents_enabled else
                "CONFIGURED" if settings.tradingagents_configured else "LOCAL_LLM_UNAVAILABLE")
    tradingagents = {
        "state": ta_state,
        "enabled": settings.tradingagents_enabled,
        "llm_mode": "LOCAL_ONLY",
        "provider": settings.tradingagents_provider.lower(),
        "local_model": settings.tradingagents_quick_model or settings.tradingagents_deep_model or None,
        "endpoint": "LOCAL_PRIVATE_ENDPOINT" if settings.tradingagents_base_url else None,
        "network_policy": "NO_EXTERNAL_LLM_EGRESS",
        "native_external_data": "DISABLED",
        "version": settings.tradingagents_version,
        "commit": settings.tradingagents_commit,
        "broker_authority": "NONE",
        "credentials_exposed": False,
    }
    return {"status": "RESEARCH_ONLY", "execution_authority": "NONE", "broker_access": False,
            "provider": provider_status(settings), "agents": list(AGENT_ROLES), "decisions": decisions,
            "tradingagents": tradingagents,
            "governance": "Only audited point-in-time evidence may enter qualification; LLM output cannot approve execution."}
