import pytest
from pydantic import ValidationError

from app.trading_controls import EngineControlRequest, StrategyStatusRequest


def test_pause_and_shadow_resume_are_the_only_available_controls() -> None:
    assert EngineControlRequest(action="pause", reason="Owner safety pause").action == "PAUSE"
    assert EngineControlRequest(action="resume_shadow", reason="Resume shadow evaluation").action == "RESUME_SHADOW"


@pytest.mark.parametrize("action", ["DEMO_AUTO", "LIVE", "RESUME", "ENABLE_ORDERS"])
def test_control_request_cannot_enable_execution(action: str) -> None:
    with pytest.raises(ValidationError):
        EngineControlRequest(action=action, reason="Unsafe control attempt")


def test_strategy_control_is_limited_to_active_and_paused() -> None:
    assert StrategyStatusRequest(status="active", reason="Owner enabled strategy").status == "ACTIVE"
    with pytest.raises(ValidationError):
        StrategyStatusRequest(status="LIVE", reason="Unsafe status")
