import pytest
from pydantic import ValidationError

from app.config import Settings


def test_localhost_development_remains_supported() -> None:
    settings = Settings(_env_file=None, app_env="development", session_cookie_secure=False,
                        sql_trust_server_certificate=True)
    assert settings.app_env == "development"


def test_external_environment_fails_closed_without_security_controls() -> None:
    with pytest.raises(ValidationError, match="External deployment security requirements"):
        Settings(_env_file=None, app_env="production")


def test_external_environment_accepts_complete_security_controls() -> None:
    settings = Settings(_env_file=None, app_env="production", auth_hash_pepper="x" * 32,
        session_cookie_secure=True, sql_trust_server_certificate=False,
        web_origins="https://aurex.example")
    assert settings.session_cookie_secure
