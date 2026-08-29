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
        cursor.execute(
            """
            SELECT TOP (1) user_id, tenant_id, email, display_name, role,
                           status, password_hash
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

        if not row or not verified or row[5] != "active":
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
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
        cursor.execute(
            """
            INSERT INTO app.auth_sessions
                (session_id, tenant_id, user_id, token_hash, expires_at_utc,
                 user_agent_hash)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (
                str(uuid4()),
                user.tenant_id,
                user.user_id,
                _token_hash(raw_token),
                expires_at,
                sha256((request.headers.get("user-agent") or "").encode()).digest(),
            ),
        )
        cursor.execute(
            "UPDATE app.users SET last_login_at_utc=SYSUTCDATETIME() WHERE user_id=%s;",
            (user.user_id,),
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
            SELECT u.user_id, u.tenant_id, u.email, u.display_name, u.role
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
