from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator

from app.config import Settings, get_settings
from app.database import open_database

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_dummy_password_hash = password_hasher.hash("Aurex-invalid-password-placeholder")


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or len(normalized) > 320:
            raise ValueError("A valid email address is required")
        return normalized


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    role: str


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return password_hasher.hash(password)


def _token_hash(token: str) -> bytes:
    return sha256(token.encode("utf-8")).digest()


def _attempt_hash(settings: Settings, value: str) -> bytes:
    pepper = settings.auth_hash_pepper or settings.sql_database
    return sha256(f"{pepper}:{value.strip().lower()}".encode("utf-8")).digest()


def _rate_limit_exceeded(settings: Settings, email_failures: int, address_failures: int) -> bool:
    return (email_failures >= settings.auth_max_email_failures or
            address_failures >= settings.auth_max_address_failures)


def _account_locked(value: datetime | None) -> bool:
    if value is None:
        return False
    locked_until = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return locked_until > datetime.now(timezone.utc)


def _audit(
    cursor: object,
    *,
    action: str,
    correlation_id: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    metadata: str | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO app.audit_logs
            (tenant_id, user_id, action_code, entity_type, entity_id,
             correlation_id, metadata_json)
        VALUES (%s, %s, %s, 'authentication', %s, %s, %s);
        """,
        (tenant_id, user_id, action, user_id, correlation_id, metadata),
    )


def login_owner(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings,
) -> AuthenticatedUser:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    with open_database(settings) as connection:
        cursor = connection.cursor()
        email_hash = _attempt_hash(settings, credentials.email)
        address_hash = _attempt_hash(settings, request.client.host if request.client else "unknown")
        cursor.execute(
            """SELECT
                 SUM(CASE WHEN email_hash=%s AND succeeded=0 THEN 1 ELSE 0 END),
                 SUM(CASE WHEN remote_address_hash=%s AND succeeded=0 THEN 1 ELSE 0 END)
               FROM app.authentication_attempts
               WHERE attempted_at_utc>=DATEADD(minute,-%s,SYSUTCDATETIME())""",
            (email_hash, address_hash, settings.auth_failure_window_minutes),
        )
        attempts = cursor.fetchone() or (0, 0)
        if _rate_limit_exceeded(
            settings, int(attempts[0] or 0), int(attempts[1] or 0),
        ):
            _audit(cursor, action="auth.login.rate_limited", correlation_id=correlation_id,
                   metadata='{"reason":"attempt_window_exceeded"}')
            connection.commit()
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Sign-in is temporarily unavailable. Try again later.")
        cursor.execute(
            """
            SELECT TOP (1) user_id, tenant_id, email, display_name, role,
                           status, password_hash,locked_until_utc,failed_login_count,mfa_required
            FROM app.users
            WHERE LOWER(email)=LOWER(%s);
            """,
            (str(credentials.email),),
        )
        row = cursor.fetchone()
        stored_hash = row[6] if row and row[6] else _dummy_password_hash
        verified = False
        try:
            verified = password_hasher.verify(stored_hash, credentials.password)
        except (VerifyMismatchError, InvalidHashError):
            verified = False

        locked = bool(row and _account_locked(row[7]))
        if not row or not verified or row[5] != "active" or locked:
            cursor.execute(
                """INSERT app.authentication_attempts
                     (authentication_attempt_id,email_hash,remote_address_hash,succeeded,failure_code)
                   VALUES(%s,%s,%s,0,%s)""",
                (str(uuid4()), email_hash, address_hash, "ACCOUNT_LOCKED" if locked else "INVALID_CREDENTIALS"),
            )
            if row:
                cursor.execute(
                    """UPDATE app.users SET failed_login_count=failed_login_count+1,
                         locked_until_utc=CASE WHEN failed_login_count+1>=%s
                           THEN DATEADD(minute,%s,SYSUTCDATETIME()) ELSE locked_until_utc END
                       WHERE user_id=%s""",
                    (settings.auth_max_email_failures, settings.auth_lockout_minutes, str(row[0])),
                )
            _audit(
                cursor,
                action="auth.login.failed",
                correlation_id=correlation_id,
                metadata='{"reason":"invalid_credentials"}',
            )
            connection.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        user = AuthenticatedUser(
            user_id=str(row[0]),
            tenant_id=str(row[1]),
            email=row[2],
            display_name=row[3],
            role=row[4],
        )
        raw_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        if bool(row[9]):
            cursor.execute(
                """INSERT app.authentication_attempts
                     (authentication_attempt_id,email_hash,remote_address_hash,succeeded,failure_code)
                   VALUES(%s,%s,%s,0,'MFA_REQUIRED')""",
                (str(uuid4()), email_hash, address_hash),
            )
            connection.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="MFA enrollment is required before this account can sign in")
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
        cursor.execute(
            """
            INSERT INTO app.auth_sessions
                (session_id, tenant_id, user_id, token_hash, expires_at_utc,
                 user_agent_hash,csrf_token_hash)
            VALUES (%s, %s, %s, %s, %s, %s,%s);
            """,
            (
                str(uuid4()),
                user.tenant_id,
                user.user_id,
                _token_hash(raw_token),
                expires_at,
                sha256((request.headers.get("user-agent") or "").encode()).digest(),
                _token_hash(csrf_token),
            ),
        )
        cursor.execute(
            """UPDATE app.users SET last_login_at_utc=SYSUTCDATETIME(),failed_login_count=0,
                      locked_until_utc=NULL WHERE user_id=%s;
               INSERT app.authentication_attempts
                 (authentication_attempt_id,email_hash,remote_address_hash,succeeded,failure_code)
               VALUES(%s,%s,%s,1,NULL);""",
            (user.user_id, str(uuid4()), email_hash, address_hash),
        )
        _audit(
            cursor,
            action="auth.login.succeeded",
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
        )
        connection.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name, value=csrf_token,
        max_age=settings.session_hours * 3600, httponly=False,
        secure=settings.session_cookie_secure, samesite="strict", path="/",
    )
    return user


def require_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias="aurex_session"),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    # Read the configured cookie name when it differs from the default alias.
    token = request.cookies.get(settings.session_cookie_name) or session_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT u.user_id, u.tenant_id, u.email, u.display_name, u.role,s.csrf_token_hash
            FROM app.auth_sessions s
            JOIN app.users u ON u.user_id=s.user_id AND u.tenant_id=s.tenant_id
            WHERE s.token_hash=%s AND s.revoked_at_utc IS NULL
              AND s.expires_at_utc > SYSUTCDATETIME() AND u.status='active';
            """,
            (_token_hash(token),),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get(settings.csrf_header_name)
            cookie_token = request.cookies.get(settings.csrf_cookie_name)
            if not supplied or not cookie_token or not secrets.compare_digest(supplied, cookie_token) \
                    or not secrets.compare_digest(_token_hash(supplied), bytes(row[5] or b"")):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
        cursor.execute(
            "UPDATE app.auth_sessions SET last_seen_at_utc=SYSUTCDATETIME() WHERE token_hash=%s;",
            (_token_hash(token),),
        )
        connection.commit()
    user = AuthenticatedUser(str(row[0]), str(row[1]), row[2], row[3], row[4])
    request.state.tenant_id = user.tenant_id
    request.state.user_id = user.user_id
    return user


def logout_owner(
    request: Request,
    response: Response,
    user: AuthenticatedUser,
    settings: Settings,
) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    with open_database(settings) as connection:
        cursor = connection.cursor()
        if token:
            cursor.execute(
                """
                UPDATE app.auth_sessions SET revoked_at_utc=SYSUTCDATETIME()
                WHERE token_hash=%s AND tenant_id=%s AND user_id=%s;
                """,
                (_token_hash(token), user.tenant_id, user.user_id),
            )
        _audit(
            cursor,
            action="auth.logout",
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
        )
        connection.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def authenticate_session_token(token: str | None, settings: Settings) -> AuthenticatedUser | None:
    """Authenticate a read-only streaming connection from its secure session cookie."""
    if not token:
        return None
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT u.user_id,u.tenant_id,u.email,u.display_name,u.role
               FROM app.auth_sessions s
               JOIN app.users u ON u.user_id=s.user_id AND u.tenant_id=s.tenant_id
               WHERE s.token_hash=%s AND s.revoked_at_utc IS NULL
                 AND s.expires_at_utc>SYSUTCDATETIME() AND u.status='active'""",
            (_token_hash(token),),
        )
        row = cursor.fetchone()
    return None if not row else AuthenticatedUser(
        user_id=str(row[0]), tenant_id=str(row[1]), email=str(row[2]),
        display_name=str(row[3]), role=str(row[4]),
    )
