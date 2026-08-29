import pytest
from pydantic import ValidationError

from app.config import Settings
from app.readiness import configuration_checks


def safe_settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "trading_mode": "demo",
        "ig_environment": "demo",
        "broker_environment": "demo",
        "allow_demo_trading": True,
        "allow_live_trading": False,
        "ig_api_key": "test-key",
        "ig_username": "demo-user",
        "ig_password": "demo-password",
        "ig_account_id": "DEMO123",
        "smtp_username": "test@example.com",
        "smtp_password": "app-password",
        "smtp_from_email": "test@example.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_demo_execution_requires_explicit_opt_in() -> None:
    settings = safe_settings(allow_demo_trading=False)
    assert settings.demo_execution_configured is False
    assert configuration_checks(settings)["demo_execution_opt_in"].ready is False


def test_demo_execution_configuration_can_pass() -> None:
    settings = safe_settings()
    assert settings.demo_execution_configured is True
    assert configuration_checks(settings)["demo_only_configuration"].ready is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("allow_live_trading", True), ("ig_environment", "live"), ("broker_environment", "live")],
)
def test_live_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        safe_settings(**{field: value})


def test_worker_cannot_lower_model_evidence_floor() -> None:
    with pytest.raises(ValidationError):
        safe_settings(model_minimum_rows=999)
    with pytest.raises(ValidationError):
        safe_settings(model_minimum_rows=1999)
