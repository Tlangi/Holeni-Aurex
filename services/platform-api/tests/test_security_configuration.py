import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import health_ready


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


def test_production_allows_trusted_certificate_only_for_loopback_sql() -> None:
    settings = Settings(_env_file=None, app_env="production", auth_hash_pepper="x" * 32,
        session_cookie_secure=True, sql_host="127.0.0.1", sql_server="localhost\\SQLEXPRESS",
        sql_trust_server_certificate=True, web_origins="https://holeniaurex.co.za")
    assert settings.sql_trust_server_certificate


def test_production_rejects_trusted_certificate_for_remote_sql() -> None:
    with pytest.raises(ValidationError, match="SQL_TRUST_SERVER_CERTIFICATE"):
        Settings(_env_file=None, app_env="production", auth_hash_pepper="x" * 32,
            session_cookie_secure=True, sql_host="10.0.0.5", sql_server="10.0.0.5",
            sql_trust_server_certificate=True, web_origins="https://holeniaurex.co.za")


def test_public_readiness_response_does_not_disclose_internal_components(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", lambda _settings: (True, "connected:secret-host"))
    response = health_ready()
    assert response.body == b'{"status":"ready"}'
