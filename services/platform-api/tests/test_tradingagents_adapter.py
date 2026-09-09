from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.tradingagents_adapter import AurexTradingAgentsContext, TradingAgentsResearchDecision


NOW = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)


def item(source: str = "canonical_m1", **values: object) -> dict[str, object]:
    return {"source": source, "available_at_utc": NOW - timedelta(minutes=1),
            "values": values or {"momentum": 0.2}, "provenance_id": str(uuid4())}


def context(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "market": "USDJPY", "asset_class": "FX", "decision_time_utc": NOW,
        "data_cutoff_utc": NOW - timedelta(seconds=1), "horizon_minutes": 60,
        "market_snapshot_id": uuid4(), "market_features": [item()],
        "macro_evidence": [item("audited_macro", rate_differential=1.2)],
        "cost_snapshot": item("ig_observed_cost", spread_points=1.1),
        "model_outputs": [item("aurex_model", probability=0.56)],
    }
    value.update(changes)
    return value


def local_settings(**changes: object) -> Settings:
    value = {"tradingagents_enabled": True, "tradingagents_provider": "openai_compatible",
             "tradingagents_base_url": "http://127.0.0.1:11434/v1",
             "tradingagents_quick_model": "local-fixture"}
    value.update(changes)
    return Settings(**value)


def test_context_is_point_in_time_and_stably_hashed() -> None:
    parsed = AurexTradingAgentsContext.model_validate(context())
    assert parsed.snapshot_hash(local_settings()) == parsed.snapshot_hash(local_settings())


def test_future_item_is_rejected() -> None:
    future = item()
    future["available_at_utc"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="POINT_IN_TIME_VIOLATION"):
        AurexTradingAgentsContext.model_validate(context(market_features=[future]))


@pytest.mark.parametrize("secret", [
    {"ig_api_key": "FAKE_IG_SECRET"},
    {"notes": "Authorization: Bearer FAKE_SESSION_TOKEN"},
    {"database_credentials": "FAKE_SQL_SECRET"},
])
def test_secret_material_never_enters_context(secret: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="SECRET_MATERIAL_REJECTED"):
        AurexTradingAgentsContext.model_validate(context(market_features=[item(**secret)]))


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1", "http://llm.example/v1", "http://8.8.8.8:8000/v1",
    "http://0.0.0.0:11434/v1", "http://localhost.evil:11434/v1",
])
def test_external_endpoint_configuration_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="CONFIG_REJECTED_EXTERNAL_ENDPOINT"):
        local_settings(tradingagents_base_url=url)


def test_cloud_provider_and_fallback_are_rejected() -> None:
    with pytest.raises(ValidationError, match="PROVIDER_NOT_LOCAL"):
        local_settings(tradingagents_provider="openai")


def test_tradingagents_has_no_execution_contract() -> None:
    forbidden = {"order", "size", "broker", "promote", "risk_override", "position"}
    assert not forbidden.intersection(TradingAgentsResearchDecision.model_fields)
