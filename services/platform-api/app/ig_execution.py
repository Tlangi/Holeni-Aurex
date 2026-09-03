from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import sleep
from typing import Callable

import requests

from app.config import Settings
from app.ig_demo import IGDemoClient, IGDemoUnavailable


class IGExecutionBlocked(RuntimeError):
    pass


class IGSubmissionUnknown(RuntimeError):
    pass


class IGExecutionRejected(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__("IG Demo rejected the order")
        self.reason = reason[:100]


@dataclass(frozen=True)
class ExecutionGate:
    readiness_status: str
    engine_mode: str
    new_orders_enabled: bool
    intent_status: str
    account_id: str
    market_readiness_status: str


@dataclass(frozen=True)
class ExperimentalExecutionGate:
    feature_enabled: bool
    orchestrator_decision: str
    account_id: str
    environment: str
    live_trading_enabled: bool


@dataclass(frozen=True)
class ExperimentalCloseGate:
    account_id: str
    environment: str
    live_trading_enabled: bool


@dataclass(frozen=True)
class OrderSubmission:
    epic: str
    direction: str
    size: Decimal
    stop_level: Decimal
    take_profit_level: Decimal
    currency_code: str
    expiry: str
    client_reference: str


@dataclass(frozen=True)
class DealAcknowledgement:
    deal_reference: str


@dataclass(frozen=True)
class DealConfirmation:
    accepted: bool
    deal_reference: str
    deal_id: str | None
    status: str
    reason: str
    level: Decimal | None


def assert_execution_gate(settings: Settings, gate: ExecutionGate) -> None:
    if not settings.demo_execution_configured:
        raise IGExecutionBlocked("Explicit IG Demo execution configuration is disabled")
    if settings.allow_live_trading or settings.ig_environment != "demo" or settings.broker_environment != "demo":
        raise IGExecutionBlocked("Live trading configuration is forbidden")
    if gate.account_id != settings.ig_account_id:
        raise IGExecutionBlocked("Authenticated account does not match IG_ACCOUNT_ID")
    if gate.readiness_status != "READY":
        raise IGExecutionBlocked("Trading readiness is not READY")
    if gate.market_readiness_status != "READY":
        raise IGExecutionBlocked("The selected market is not READY")
    if gate.engine_mode != "DEMO_AUTO" or not gate.new_orders_enabled:
        raise IGExecutionBlocked("Engine is not enabled for DEMO_AUTO")
    if gate.intent_status != "RISK_APPROVED":
        raise IGExecutionBlocked("Only a newly risk-approved intent may be submitted")


def assert_experimental_execution_gate(settings: Settings, gate: ExperimentalExecutionGate) -> None:
    """Final narrow transport lock; the isolated orchestrator owns all other gates."""
    if not settings.experimental_demo_configured or not gate.feature_enabled:
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_FEATURE_DISABLED")
    if settings.allow_live_trading or gate.live_trading_enabled:
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED")
    if settings.ig_environment != "demo" or settings.broker_environment != "demo" \
            or gate.environment.lower() != "demo":
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED")
    if gate.account_id != settings.ig_account_id:
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED")
    if gate.orchestrator_decision != "ELIGIBLE":
        raise IGExecutionBlocked("Experimental orchestrator did not approve this attempt")


def assert_experimental_close_gate(settings: Settings, gate: ExperimentalCloseGate) -> None:
    """Allow safe position management even after entry opt-in is disabled or expired."""
    if settings.allow_live_trading or gate.live_trading_enabled:
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED")
    if settings.ig_environment != "demo" or settings.broker_environment != "demo" \
            or gate.environment.lower() != "demo" or gate.account_id != settings.ig_account_id:
        raise IGExecutionBlocked("EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED")


def validate_order_submission(item: OrderSubmission) -> None:
    if item.direction not in {"BUY", "SELL"}:
        raise ValueError("Invalid direction")
    if not item.epic.startswith(("CS.D.", "IX.D.")) or not item.epic.endswith(".IP"):
        raise ValueError("Unsupported epic")
    if item.size <= 0 or item.stop_level <= 0 or item.take_profit_level <= 0:
        raise ValueError("Size, stop and take-profit must be positive")
    if len(item.currency_code) != 3 or not item.currency_code.isalpha():
        raise ValueError("Invalid dealing currency")
    if not item.client_reference.startswith("AUREX-") or len(item.client_reference) > 80:
        raise ValueError("Invalid Aurex client reference")


class IGDemoExecutionAdapter:
    """Narrow IG Demo dealing adapter; no caller is wired to it until readiness passes."""

    def __init__(self, settings: Settings, client: IGDemoClient, *, sleeper: Callable[[float], None] = sleep) -> None:
        if client.base_url != "https://demo-api.ig.com/gateway/deal":
            raise IGExecutionBlocked("Execution adapter requires the immutable IG Demo endpoint")
        if not client.account_id:
            raise IGExecutionBlocked("IG Demo client is not authenticated")
        self.settings = settings
        self.client = client
        self.sleeper = sleeper

    def submit(self, submission: OrderSubmission, gate: ExecutionGate) -> DealAcknowledgement:
        assert_execution_gate(self.settings, gate)
        return self._submit_once(submission)

    def submit_experimental(
        self, submission: OrderSubmission, gate: ExperimentalExecutionGate,
    ) -> DealAcknowledgement:
        assert_experimental_execution_gate(self.settings, gate)
        return self._submit_once(submission)

    def _submit_once(self, submission: OrderSubmission) -> DealAcknowledgement:
        validate_order_submission(submission)
        try:
            response = self.client.session.post(
                f"{self.client.base_url}/positions/otc",
                headers={"Version": "2", "Content-Type": "application/json"},
                json={
                    "currencyCode": submission.currency_code,
                    "dealReference": submission.client_reference,
                    "direction": submission.direction,
                    "epic": submission.epic,
                    "expiry": submission.expiry,
                    "forceOpen": True,
                    "guaranteedStop": False,
                    "orderType": "MARKET",
                    "size": float(submission.size),
                    "stopLevel": float(submission.stop_level),
                    "limitLevel": float(submission.take_profit_level),
                    "timeInForce": "FILL_OR_KILL",
                    "trailingStop": False,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            # The request may have reached IG. Never retry this submission.
            raise IGSubmissionUnknown("IG Demo submission outcome is unknown; reconcile before retry") from exc
        payload = self._payload(response)
        if response.status_code not in {200, 201}:
            raise IGExecutionRejected(str(payload.get("errorCode") or f"HTTP_{response.status_code}"))
        reference = str(payload.get("dealReference") or "")
        if not reference:
            raise IGSubmissionUnknown("IG Demo acknowledgement omitted dealReference")
        return DealAcknowledgement(reference)

    def close_experimental(
        self, *, deal_id: str, direction: str, size: Decimal, epic: str,
        expiry: str, gate: ExperimentalCloseGate,
    ) -> DealAcknowledgement:
        assert_experimental_close_gate(self.settings, gate)
        if not deal_id or direction not in {"BUY", "SELL"} or size <= 0:
            raise ValueError("Invalid experimental close request")
        try:
            response = self.client.session.post(
                f"{self.client.base_url}/positions/otc",
                headers={"Version": "1", "Content-Type": "application/json", "_method": "DELETE"},
                json={"dealId": deal_id, "direction": direction, "epic": epic,
                      "expiry": expiry, "orderType": "MARKET", "size": float(size),
                      "timeInForce": "FILL_OR_KILL"}, timeout=20,
            )
        except requests.RequestException as exc:
            raise IGSubmissionUnknown("IG Demo close outcome is unknown; reconcile before retry") from exc
        payload = self._payload(response)
        if response.status_code not in {200, 201}:
            raise IGExecutionRejected(str(payload.get("errorCode") or f"HTTP_{response.status_code}"))
        reference = str(payload.get("dealReference") or "")
        if not reference:
            raise IGSubmissionUnknown("IG Demo close acknowledgement omitted dealReference")
        return DealAcknowledgement(reference)

    def confirm(self, deal_reference: str, *, attempts: int = 10) -> DealConfirmation:
        if not deal_reference or attempts < 1 or attempts > 20:
            raise ValueError("Invalid confirmation request")
        for attempt in range(attempts):
            try:
                response = self.client.session.get(
                    f"{self.client.base_url}/confirms/{deal_reference}",
                    headers={"Version": "1"}, timeout=15,
                )
            except requests.RequestException as exc:
                raise IGSubmissionUnknown("IG Demo confirmation is unavailable") from exc
            if response.status_code == 404:
                if attempt + 1 < attempts:
                    self.sleeper(1)
                continue
            payload = self._payload(response)
            if response.status_code != 200:
                raise IGSubmissionUnknown("IG Demo confirmation returned an uncertain response")
            accepted = str(payload.get("dealStatus") or "").upper() == "ACCEPTED" \
                and str(payload.get("status") or "").upper() != "REJECTED"
            return DealConfirmation(
                accepted=accepted,
                deal_reference=str(payload.get("dealReference") or deal_reference),
                deal_id=str(payload.get("dealId")) if payload.get("dealId") else None,
                status=str(payload.get("status") or "UNKNOWN").upper(),
                reason=str(payload.get("reason") or "UNKNOWN").upper()[:100],
                level=Decimal(str(payload["level"])) if payload.get("level") is not None else None,
            )
        raise IGSubmissionUnknown("IG Demo confirmation timed out; reconciliation is required")

    @staticmethod
    def _payload(response: requests.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise IGSubmissionUnknown("IG Demo returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise IGSubmissionUnknown("IG Demo returned an unexpected response")
        return payload
