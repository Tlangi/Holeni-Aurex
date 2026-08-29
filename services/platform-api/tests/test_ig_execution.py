from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

from app.config import Settings
from app.ig_execution import (
    ExecutionGate, IGDemoExecutionAdapter, IGExecutionBlocked, IGSubmissionUnknown,
    OrderSubmission, assert_execution_gate, validate_order_submission,
)


def settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None, "trading_mode": "demo", "allow_demo_trading": True,
        "allow_live_trading": False, "ig_environment": "demo", "broker_environment": "demo",
        "ig_api_key": "key", "ig_username": "user", "ig_password": "password",
        "ig_account_id": "DEMO1",
    }
    values.update(overrides)
    return Settings(**values)


def gate(**overrides: object) -> ExecutionGate:
    values = {"readiness_status": "READY", "engine_mode": "DEMO_AUTO",
              "new_orders_enabled": True, "intent_status": "RISK_APPROVED", "account_id": "DEMO1",
              "market_readiness_status": "READY"}
    values.update(overrides)
    return ExecutionGate(**values)


def test_execution_gate_blocks_a_market_that_is_not_ready() -> None:
    with pytest.raises(IGExecutionBlocked, match="selected market"):
        assert_execution_gate(settings(), gate(market_readiness_status="NOT_READY"))


def order() -> OrderSubmission:
    return OrderSubmission("CS.D.EURUSD.CFD.IP", "BUY", Decimal("1"), Decimal("1.1"),
                           Decimal("1.2"), "USD", "-", "AUREX-TEST-123")


class Response:
    def __init__(self, status: int, payload: dict[str, object]) -> None:
        self.status_code, self.payload = status, payload

    def json(self) -> dict[str, object]:
        return self.payload


class Session:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail, self.posts = fail, 0

    def post(self, *args: object, **kwargs: object) -> Response:
        self.posts += 1
        if self.fail:
            raise requests.Timeout("unknown")
        return Response(200, {"dealReference": "REF-1"})

    def get(self, *args: object, **kwargs: object) -> Response:
        return Response(200, {"dealReference": "REF-1", "dealId": "DEAL-1",
                              "dealStatus": "ACCEPTED", "status": "OPEN", "level": 1.15})


def adapter(session: Session) -> IGDemoExecutionAdapter:
    client = SimpleNamespace(base_url="https://demo-api.ig.com/gateway/deal", account_id="DEMO1", session=session)
    return IGDemoExecutionAdapter(settings(), client, sleeper=lambda _: None)


@pytest.mark.parametrize("blocked_gate", [gate(readiness_status="NOT_READY"), gate(engine_mode="SHADOW"),
                                            gate(intent_status="WOULD_SUBMIT"), gate(account_id="OTHER")])
def test_submission_is_blocked_unless_every_gate_passes(blocked_gate: ExecutionGate) -> None:
    session = Session()
    with pytest.raises(IGExecutionBlocked):
        adapter(session).submit(order(), blocked_gate)
    assert session.posts == 0


def test_successful_demo_acknowledgement_and_confirmation() -> None:
    execution = adapter(Session())
    acknowledgement = execution.submit(order(), gate())
    confirmation = execution.confirm(acknowledgement.deal_reference)
    assert acknowledgement.deal_reference == "REF-1"
    assert confirmation.accepted and confirmation.deal_id == "DEAL-1"


def test_submission_timeout_is_unknown_and_is_not_retried() -> None:
    session = Session(fail=True)
    with pytest.raises(IGSubmissionUnknown):
        adapter(session).submit(order(), gate())
    assert session.posts == 1


def test_germany_40_demo_epic_is_within_the_narrow_execution_contract() -> None:
    validate_order_submission(OrderSubmission(
        "IX.D.DAX.BMU.IP", "SELL", Decimal("0.5"), Decimal("26000"),
        Decimal("25000"), "EUR", "-", "AUREX-TEST-DAX",
    ))
