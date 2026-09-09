import asyncio
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from app.config import Settings
from app.llm_runtime import OpenAICompatibleRuntime, ProviderUnavailable


def decision_payload(**changes: object) -> dict[str, object]:
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    value: dict[str, object] = {
        "market": "USDJPY", "requested_analysis_utc": now.isoformat(), "direction": "REJECT",
        "confidence": 0.8, "expected_horizon_minutes": 60, "reasoning_summary": "Cost evidence missing.",
        "risk_flags": ["EXECUTION_COST_UNKNOWN"], "market_snapshot_id": str(uuid4()),
        "prompt_version": "forex-v1", "provider": "test", "model": "fixture",
        "agent": "TRADE_REJECTION", "market_data_cutoff_utc": (now-timedelta(minutes=1)).isoformat(),
        "evidence_quality": "POINT_IN_TIME_VERIFIED", "audit_status": "PASS",
    }
    value.update(changes)
    return value


def settings(**changes: object) -> Settings:
    values = {"intelligence_enabled": True, "llm_provider": "openai_compatible",
              "llm_model_fast": "fixture", "llm_base_url": "http://127.0.0.1:11434/v1", "llm_api_key": "secret",
              "llm_max_retries": 1, "llm_circuit_failure_threshold": 2}
    values.update(changes)
    return Settings(**values)


def test_success_parses_strict_structured_decision_without_leaking_secret() -> None:
    def transport(url, headers, payload, timeout):
        assert headers["Authorization"] == "Bearer secret"
        return 200, {"choices": [{"message": {"content": json.dumps(decision_payload())}}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 20}}, {}
    runtime = OpenAICompatibleRuntime(settings(), transport=transport)
    result = asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))
    assert result.decision.direction.value == "REJECT" and result.input_tokens == 10
    assert "secret" not in json.dumps(runtime.health())


def test_rate_limit_retries_once_then_succeeds() -> None:
    calls = 0
    def transport(*args):
        nonlocal calls
        calls += 1
        if calls == 1: return 429, {}, {"Retry-After": "0"}
        return 200, {"choices": [{"message": {"content": decision_payload()}}]}, {}
    result = asyncio.run(OpenAICompatibleRuntime(settings(), transport=transport, sleep=lambda _: None).invoke(
        system_prompt="safe", user_prompt="facts"))
    assert calls == 2 and result.attempts == 2


def test_malformed_output_fails_without_becoming_neutral() -> None:
    runtime = OpenAICompatibleRuntime(settings(), transport=lambda *args: (200, {"choices": []}, {}))
    with pytest.raises(ProviderUnavailable, match="MALFORMED_PROVIDER_RESPONSE"):
        asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))


def test_schema_failure_is_explicit() -> None:
    invalid = decision_payload(direction="LONG", evidence_quality="INSUFFICIENT")
    runtime = OpenAICompatibleRuntime(settings(), transport=lambda *args: (
        200, {"choices": [{"message": {"content": json.dumps(invalid)}}]}, {}))
    with pytest.raises(ProviderUnavailable, match="SCHEMA_VALIDATION_FAILED"):
        asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))


def test_circuit_opens_after_bounded_failures() -> None:
    calls = 0
    def transport(*args):
        nonlocal calls
        calls += 1
        return 503, {}, {}
    runtime = OpenAICompatibleRuntime(settings(llm_max_retries=0), transport=transport, sleep=lambda _: None)
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))
    with pytest.raises(ProviderUnavailable, match="LLM_CIRCUIT_OPEN"):
        asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))
    assert calls == 2 and runtime.health()["status"] == "CIRCUIT_OPEN"


def test_not_configured_provider_fails_closed() -> None:
    runtime = OpenAICompatibleRuntime(Settings())
    with pytest.raises(ProviderUnavailable, match="NOT_CONFIGURED"):
        asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="facts"))


def test_redirect_is_not_followed() -> None:
    runtime = OpenAICompatibleRuntime(
        settings(), transport=lambda *args: (302, {}, {"Location": "https://api.openai.com"})
    )
    with pytest.raises(ProviderUnavailable, match="PROVIDER_HTTP_302"):
        asyncio.run(runtime.invoke(system_prompt="safe", user_prompt="synthetic facts"))
