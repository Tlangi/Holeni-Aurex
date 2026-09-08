from collections.abc import Iterator
from contextlib import contextmanager

import pymssql

from app.config import Settings


class DatabaseUnavailable(RuntimeError):
    """Raised without leaking raw driver or connection details."""


@contextmanager
def open_database(settings: Settings, *, query_timeout_seconds: int = 10) -> Iterator[pymssql.Connection]:
    try:
        connection = pymssql.connect(
            server=settings.sql_host,
            port=settings.sql_port,
            user=settings.sql_username,
            password=settings.sql_password,
            database=settings.sql_database,
            login_timeout=5,
            timeout=query_timeout_seconds,
            autocommit=False,
        )
    except pymssql.Error as exc:
        raise DatabaseUnavailable("SQL Server is unavailable") from exc

    try:
        yield connection
    finally:
        connection.close()


def check_database(settings: Settings) -> tuple[bool, str]:
    if not settings.database_configured:
        return False, "not_configured"

    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT DB_NAME()")
            database_name = cursor.fetchone()[0]
            return database_name == settings.sql_database, "connected"
    except DatabaseUnavailable:
        return False, "unavailable"


def operational_schema_ready(settings: Settings) -> bool:
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(1)
                FROM sys.tables t
                JOIN sys.schemas s ON s.schema_id=t.schema_id
                WHERE s.name='app' AND t.name IN ('auth_sessions', 'sync_runs', 'position_events');
                """
            )
            return int(cursor.fetchone()[0]) == 3
    except DatabaseUnavailable:
        return False


def tenant_has_trading_account(settings: Settings, tenant_id: str) -> bool:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM app.trading_accounts WHERE tenant_id=%s;", (tenant_id,)
        )
        return cursor.fetchone() is not None
