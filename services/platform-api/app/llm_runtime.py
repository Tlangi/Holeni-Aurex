from __future__ import annotations

"""Bounded research-only LLM transport. This module has no database or broker access."""

import asyncio
from dataclasses import dataclass
import json
import random
from threading import Lock
import time
from typing import Callable, Mapping, Any

import requests
from pydantic import ValidationError

from app.config import Settings
from app.intelligence import AgentDecision


class ProviderUnavailable(RuntimeError):
    pass


class MalformedProviderResponse(ProviderUnavailable):
    pass


@dataclass(frozen=True)
class InvocationResult:
    decision: AgentDecision
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: str | None
    attempts: int


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float | None = None
    last_success_utc: str | None = None
    last_failure_utc: str | None = None
    last_latency_ms: int | None = None
    last_error_code: str | None = None


Transport = Callable[[str, Mapping[str, str], Mapping[str, Any], float], tuple[int, Mapping[str, Any], Mapping[str, str]]]


def _requests_transport(url: str, headers: Mapping[str, str], payload: Mapping[str, Any],
                        timeout: float) -> tuple[int, Mapping[str, Any], Mapping[str, str]]:
    # Redirects are disabled so a permitted loopback/private endpoint cannot
    # bounce a research payload to a public provider.
    response = requests.post(
        url, headers=dict(headers), json=dict(payload), timeout=timeout, allow_redirects=False
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body, response.headers


class OpenAICompatibleRuntime:
    """OpenAI-compatible structured invocation with bounded retry and circuit breaking."""

    def __init__(self, settings: Settings, *, transport: Transport = _requests_transport,
                 cooldown_seconds: int = 300, sleep: Callable[[float], None] = time.sleep) -> None:
        self.settings, self.transport, self.cooldown_seconds, self.sleep = settings, transport, cooldown_seconds, sleep
        self.state = CircuitState()
        self._lock = Lock()

    def health(self) -> dict[str, object]:
        now = time.monotonic()
        circuit_open = self.state.opened_at is not None and now - self.state.opened_at < self.cooldown_seconds
        if not self.settings.intelligence_enabled:
            status = "DISABLED"
        elif not self.settings.intelligence_provider_configured:
            status = "NOT_CONFIGURED"
        elif circuit_open:
            status = "CIRCUIT_OPEN"
        elif self.state.last_error_code:
            status = "DEGRADED"
        else:
            status = "HEALTHY" if self.state.last_success_utc else "CONFIGURED"
        return {"status": status, "failure_count": self.state.failures, "circuit_open": circuit_open,
                "last_success_utc": self.state.last_success_utc, "last_failure_utc": self.state.last_failure_utc,
                "last_latency_ms": self.state.last_latency_ms, "last_error_code": self.state.last_error_code}

    async def invoke(self, *, system_prompt: str, user_prompt: str, deep: bool = False) -> InvocationResult:
        return await asyncio.to_thread(self._invoke_sync, system_prompt, user_prompt, deep)

    def _invoke_sync(self, system_prompt: str, user_prompt: str, deep: bool) -> InvocationResult:
        if not self.settings.intelligence_provider_configured:
            raise ProviderUnavailable("LLM_PROVIDER_NOT_CONFIGURED")
        self._guard_circuit()
        model = self.settings.llm_model_deep if deep else self.settings.llm_model_fast
        model = model or self.settings.llm_model_deep or self.settings.llm_model_fast
        # LOCAL_ONLY has no provider defaults and therefore no cloud fallback.
        base_url = self.settings.llm_base_url
        if not base_url:
            raise ProviderUnavailable("LLM_BASE_URL_NOT_CONFIGURED")
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        payload = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}]}
        started, attempts = time.monotonic(), 0
        for attempts in range(1, self.settings.llm_max_retries + 2):
            try:
                status, body, response_headers = self.transport(url, headers, payload, self.settings.llm_timeout_seconds)
                if status in {408, 429, 500, 502, 503, 504}:
                    raise ProviderUnavailable(f"PROVIDER_HTTP_{status}")
                if status < 200 or status >= 300:
                    raise MalformedProviderResponse(f"PROVIDER_HTTP_{status}")
                result = self._parse(body, attempts, int((time.monotonic() - started) * 1000))
                self._success(result.latency_ms)
                return result
            except (requests.Timeout, requests.ConnectionError, ProviderUnavailable, ValidationError, KeyError,
                    IndexError, TypeError, json.JSONDecodeError) as exc:
                code = self._error_code(exc)
                if attempts > self.settings.llm_max_retries or isinstance(exc, (MalformedProviderResponse, ValidationError)):
                    self._failure(code)
                    raise ProviderUnavailable(code) from None
                retry_after = response_headers.get("Retry-After") if "response_headers" in locals() else None
                delay = min(float(retry_after), 10.0) if retry_after and retry_after.isdigit() else min(2 ** (attempts - 1), 8)
                self.sleep(delay + random.uniform(0, 0.05))
        raise ProviderUnavailable("PROVIDER_FAILED")

    def _parse(self, body: Mapping[str, Any], attempts: int, latency_ms: int) -> InvocationResult:
        content = body["choices"][0]["message"]["content"]
        structured = json.loads(content) if isinstance(content, str) else content
        decision = AgentDecision.model_validate(structured)
        usage = body.get("usage") or {}
        return InvocationResult(decision, latency_ms, usage.get("prompt_tokens"),
                                usage.get("completion_tokens"), None, attempts)

    def _guard_circuit(self) -> None:
        with self._lock:
            if self.state.opened_at is None:
                return
            if time.monotonic() - self.state.opened_at < self.cooldown_seconds:
                raise ProviderUnavailable("LLM_CIRCUIT_OPEN")
            self.state.opened_at = None
            self.state.failures = 0

    def _success(self, latency_ms: int) -> None:
        from datetime import datetime, timezone
        with self._lock:
            self.state.failures = 0; self.state.opened_at = None; self.state.last_error_code = None
            self.state.last_latency_ms = latency_ms; self.state.last_success_utc = datetime.now(timezone.utc).isoformat()

    def _failure(self, code: str) -> None:
        from datetime import datetime, timezone
        with self._lock:
            self.state.failures += 1; self.state.last_error_code = code
            self.state.last_failure_utc = datetime.now(timezone.utc).isoformat()
            if self.state.failures >= self.settings.llm_circuit_failure_threshold:
                self.state.opened_at = time.monotonic()

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, requests.Timeout): return "PROVIDER_TIMEOUT"
        if isinstance(exc, ValidationError): return "SCHEMA_VALIDATION_FAILED"
        if isinstance(exc, (KeyError, IndexError, TypeError, json.JSONDecodeError)): return "MALFORMED_PROVIDER_RESPONSE"
        text = str(exc)
        return text if text.startswith(("PROVIDER_", "LLM_")) else "PROVIDER_UNAVAILABLE"
