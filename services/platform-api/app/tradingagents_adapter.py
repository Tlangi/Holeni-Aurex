from __future__ import annotations

"""Strict Aurex-to-TradingAgents research boundary.

This module intentionally has no broker, execution, position, credential, or
model-promotion imports. It builds a minimal point-in-time snapshot for the
isolated worker and validates the structured research result returned by it.
"""

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import Settings
from app.intelligence import Direction, EvidenceQuality


UPSTREAM_REPOSITORY = "https://github.com/TauricResearch/TradingAgents.git"
ALLOWED_PROVIDERS = frozenset({"ollama", "openai_compatible"})
FORBIDDEN_KEYS = frozenset({
    "password", "api_key", "apikey", "secret", "token", "authorization",
    "cookie", "session", "smtp_password", "sql_password", "ig_password",
    "ig_api_key", "database_url", "connection_string", "filesystem_path",
})
SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+\-/=]{8,}|(?:password|api[_-]?key|secret|token)\s*[:=])"
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class AssetClass(StrEnum):
    FX = "FX"
    METAL = "METAL"
    INDEX_CFD = "INDEX_CFD"


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=80)
    available_at_utc: datetime
    values: dict[str, Any]
    provenance_id: str = Field(min_length=1, max_length=160)


class AurexTradingAgentsContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID = Field(default_factory=uuid4)
    market: str = Field(pattern=r"^[A-Z0-9]{6,12}$")
    asset_class: AssetClass
    decision_time_utc: datetime
    data_cutoff_utc: datetime
    horizon_minutes: int = Field(ge=1, le=1440)
    market_snapshot_id: UUID
    market_features: list[ContextItem] = Field(max_length=12)
    macro_evidence: list[ContextItem] = Field(default_factory=list, max_length=20)
    event_evidence: list[ContextItem] = Field(default_factory=list, max_length=20)
    cost_snapshot: ContextItem
    model_outputs: list[ContextItem] = Field(default_factory=list, max_length=20)
    native_agent_evidence: list[ContextItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def enforce_cutoff_and_minimization(self) -> "AurexTradingAgentsContext":
        decision, cutoff = _utc(self.decision_time_utc), _utc(self.data_cutoff_utc)
        if cutoff > decision:
            raise ValueError("data cutoff cannot be later than decision time")
        items = [*self.market_features, *self.macro_evidence, *self.event_evidence,
                 self.cost_snapshot, *self.model_outputs, *self.native_agent_evidence]
        if any(_utc(item.available_at_utc) > cutoff for item in items):
            raise ValueError("POINT_IN_TIME_VIOLATION")
        reject_secrets(self.model_dump(mode="json"))
        return self

    def canonical_payload(self, settings: Settings) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded) > settings.tradingagents_max_context_chars:
            raise ValueError("TRADINGAGENTS_CONTEXT_LIMIT_EXCEEDED")
        reject_secrets(payload)
        return payload

    def snapshot_hash(self, settings: Settings) -> str:
        encoded = json.dumps(
            self.canonical_payload(settings), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TradingAgentsResearchDecision(BaseModel):
    """Concise audit evidence only; never raw chain-of-thought."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    market: str = Field(pattern=r"^[A-Z0-9]{6,12}$")
    data_cutoff_utc: datetime
    role: str = Field(min_length=1, max_length=60)
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    horizon_minutes: int = Field(ge=1, le=1440)
    reasoning_summary: str = Field(min_length=1, max_length=2000)
    supporting_factors: list[str] = Field(default_factory=list, max_length=20)
    opposing_factors: list[str] = Field(default_factory=list, max_length=20)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    feature_suggestions: list[str] = Field(default_factory=list, max_length=20)
    model_critique: list[str] = Field(default_factory=list, max_length=20)
    regime: str = Field(max_length=40)
    evidence_quality: EvidenceQuality
    audit_status: str = Field(pattern=r"^(PASS|FAIL|PENDING)$")
    local_model: str = Field(min_length=1, max_length=160)
    tradingagents_version: str = Field(min_length=1, max_length=40)
    tradingagents_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    prompt_version: str = Field(min_length=1, max_length=80)
    input_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reasoning_summary")
    @classmethod
    def prohibit_chain_of_thought(cls, value: str) -> str:
        if "chain of thought" in value.lower() or "hidden reasoning" in value.lower():
            raise ValueError("raw chain-of-thought must not be stored")
        return value

    @model_validator(mode="after")
    def fail_closed(self) -> "TradingAgentsResearchDecision":
        verified = (
            self.audit_status == "PASS"
            and self.evidence_quality == EvidenceQuality.POINT_IN_TIME_VERIFIED
        )
        if not verified and self.direction not in {Direction.NEUTRAL, Direction.REJECT}:
            raise ValueError("unverified TradingAgents evidence must fail closed")
        reject_secrets(self.model_dump(mode="json"))
        return self


def reject_secrets(value: Any, path: str = "context") -> None:
    """Reject secret-shaped keys and values before request, persistence, or logs."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_KEYS or any(
                token in normalized for token in ("password", "credential", "api_key", "secret")
            ):
                raise ValueError(f"SECRET_MATERIAL_REJECTED:{path}.{key}")
            reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_PATTERN.search(value):
        raise ValueError(f"SECRET_MATERIAL_REJECTED:{path}")


def tradingagents_status(settings: Settings) -> dict[str, Any]:
    if not settings.tradingagents_enabled:
        state = "DISABLED"
    elif not settings.tradingagents_configured:
        state = "LOCAL_LLM_UNAVAILABLE"
    else:
        state = "CONFIGURED"
    return {
        "state": state,
        "enabled": settings.tradingagents_enabled,
        "llm_mode": "LOCAL_ONLY",
        "provider": settings.tradingagents_provider,
        "local_model": settings.tradingagents_quick_model or settings.tradingagents_deep_model or None,
        "endpoint": "LOCAL_PRIVATE_ENDPOINT" if settings.tradingagents_base_url else None,
        "network_policy": "NO_EXTERNAL_LLM_EGRESS",
        "native_external_data": "DISABLED",
        "broker_authority": "NONE",
        "execution_authority": "NONE",
        "repository": UPSTREAM_REPOSITORY,
        "version": settings.tradingagents_version,
        "commit": settings.tradingagents_commit,
        "prompt_version": settings.tradingagents_prompt_version,
    }
