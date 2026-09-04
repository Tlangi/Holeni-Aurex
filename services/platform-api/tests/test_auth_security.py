from datetime import datetime, timedelta, timezone

from app.auth import _account_locked, _attempt_hash, _rate_limit_exceeded
from app.config import Settings


def test_auth_attempt_hash_is_normalized_peppered_and_non_reversible() -> None:
    first = Settings(_env_file=None, sql_database="ForexSaas", auth_hash_pepper="pepper-one")
    second = Settings(_env_file=None, sql_database="ForexSaas", auth_hash_pepper="pepper-two")
    assert _attempt_hash(first, " Owner@Example.COM ") == _attempt_hash(first, "owner@example.com")
    assert _attempt_hash(first, "owner@example.com") != _attempt_hash(second, "owner@example.com")
    assert b"owner@example.com" not in _attempt_hash(first, "owner@example.com")


def test_rate_limits_and_timezone_safe_account_lockout() -> None:
    settings = Settings(_env_file=None, auth_max_email_failures=5, auth_max_address_failures=20)
    assert not _rate_limit_exceeded(settings, 4, 19)
    assert _rate_limit_exceeded(settings, 5, 0)
    assert _rate_limit_exceeded(settings, 0, 20)
    assert _account_locked(datetime.now(timezone.utc) + timedelta(minutes=1))
    assert _account_locked((datetime.now(timezone.utc) + timedelta(minutes=1)).replace(tzinfo=None))
    assert not _account_locked(datetime.now(timezone.utc) - timedelta(minutes=1))
