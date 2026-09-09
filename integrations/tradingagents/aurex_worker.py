from __future__ import annotations

"""Isolated, tool-free TradingAgents worker for approved Aurex context only."""

import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "platform-api"))

from app.config import Settings  # noqa: E402
from app.tradingagents_adapter import (  # noqa: E402
    AurexTradingAgentsContext,
    TradingAgentsResearchDecision,
    reject_secrets,
)


SYSTEM_PROMPT = """You are an internal Aurex Forex/CFD research team operating locally.
Use only the supplied point-in-time JSON evidence. Do not call tools, browse, request more data,
or produce orders, sizes, model promotions, or execution instructions. Aurex statistical models,
qualification, deterministic risk, reconciliation, and execution remain authoritative. Return only
a concise JSON research conclusion matching the requested schema. Do not reveal chain-of-thought."""


def _safe_environment() -> None:
    forbidden = (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY",
        "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY",
        "NVIDIA_API_KEY", "AZURE_OPENAI_API_KEY", "AWS_BEARER_TOKEN_BEDROCK",
    )
    for name in forbidden:
        os.environ.pop(name, None)


def run(request: dict[str, Any]) -> dict[str, Any]:
    reject_secrets(request)
    settings = Settings(**request["configuration"])
    if not settings.tradingagents_configured:
        raise RuntimeError("LOCAL_LLM_UNAVAILABLE")
    context = AurexTradingAgentsContext.model_validate(request["context"])
    payload = context.canonical_payload(settings)

    # Import from the pinned official environment only after policy validation.
    from tradingagents.llm_clients import create_llm_client

    provider = settings.tradingagents_provider.lower()
    model = settings.tradingagents_deep_model or settings.tradingagents_quick_model
    client = create_llm_client(
        provider=provider,
        model=model,
        base_url=settings.tradingagents_base_url,
        max_retries=0,
        temperature=0,
        max_tokens=settings.tradingagents_max_output_tokens,
    )
    llm = client.get_llm()
    prompt = {
        "task": "Forex-adapted bull/bear debate, regime assessment, model critique and risk challenge",
        "asset_guidance": {
            "FX": "Use rates, macro, session, carry, technical, volatility and costs; no equity fundamentals.",
            "METAL": "Use XAU/USD, USD, yields, risk, technical, volatility and costs.",
            "INDEX_CFD": "Use broker-specific index evidence, macro, technical, volatility and costs; keep proxies classified.",
        }[context.asset_class.value],
        "output_contract": TradingAgentsResearchDecision.model_json_schema(),
        "context": payload,
        "required_metadata": {
            "run_id": str(context.run_id),
            "market": context.market,
            "data_cutoff_utc": context.data_cutoff_utc.isoformat(),
            "horizon_minutes": context.horizon_minutes,
            "local_model": model,
            "tradingagents_version": settings.tradingagents_version,
            "tradingagents_commit": settings.tradingagents_commit,
            "prompt_version": settings.tradingagents_prompt_version,
            "input_snapshot_hash": context.snapshot_hash(settings),
        },
    }
    reject_secrets(prompt)
    message = llm.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(prompt, sort_keys=True)},
    ])
    content = message.content
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    result = TradingAgentsResearchDecision.model_validate_json(content)
    expected = prompt["required_metadata"]
    actual = {
        "run_id": str(result.run_id), "market": result.market,
        "data_cutoff_utc": result.data_cutoff_utc.isoformat(),
        "horizon_minutes": result.horizon_minutes, "local_model": result.local_model,
        "tradingagents_version": result.tradingagents_version,
        "tradingagents_commit": result.tradingagents_commit,
        "prompt_version": result.prompt_version,
        "input_snapshot_hash": result.input_snapshot_hash,
    }
    if actual != expected:
        raise ValueError("TRADINGAGENTS_PROVENANCE_MISMATCH")
    reject_secrets(result.model_dump(mode="json"))
    return result.model_dump(mode="json")


def main() -> int:
    _safe_environment()
    try:
        request = json.load(sys.stdin)
        response = {"status": "SUCCEEDED", "decision": run(request), "execution_authority": "NONE"}
        print(json.dumps(response, separators=(",", ":")))
        return 0
    except Exception as exc:
        code = str(exc)
        known = (
            "CONFIG_REJECTED_EXTERNAL_ENDPOINT", "PROVIDER_NOT_LOCAL",
            "LOCAL_LLM_UNAVAILABLE", "MODEL_NOT_LOADED", "CIRCUIT_OPEN",
            "POINT_IN_TIME_VIOLATION", "SECRET_MATERIAL_REJECTED",
            "TRADINGAGENTS_PROVENANCE_MISMATCH", "TRADINGAGENTS_SNAPSHOT_MISMATCH",
        )
        safe_code = next((value for value in known if value in code), "TRADINGAGENTS_FAILED")
        print(json.dumps({"status": "FAILED", "error_code": safe_code, "execution_authority": "NONE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
