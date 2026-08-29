"""Apply a GO-delimited T-SQL migration using the configured application login."""

from pathlib import Path
from hashlib import sha256
import re
import sys

import pymssql

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.config import get_settings


def split_batches(sql: str) -> list[str]:
    return [batch.strip() for batch in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE | re.IGNORECASE) if batch.strip()]


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/apply_migration.py <migration.sql>")
        return 2

    migration_path = Path(sys.argv[1]).resolve()
    if not migration_path.is_file() or migration_path.suffix.lower() != ".sql":
        print("Migration must be an existing .sql file.")
        return 2

    settings = get_settings()
    if not settings.database_configured:
        print("SQL configuration is incomplete.")
        return 2

    try:
        with pymssql.connect(
            server=settings.sql_host,
            port=settings.sql_port,
            user=settings.sql_username,
            password=settings.sql_password,
            database=settings.sql_database,
            login_timeout=10,
            timeout=30,
            autocommit=True,
        ) as connection:
            cursor = connection.cursor()
            sql = migration_path.read_text(encoding="utf-8-sig")
            checksum = sha256(sql.encode("utf-8")).hexdigest()
            cursor.execute("""
                IF OBJECT_ID(N'app.schema_migrations', N'U') IS NULL
                BEGIN
                    CREATE TABLE app.schema_migrations
                    (
                        migration_id varchar(100) NOT NULL CONSTRAINT PK_schema_migrations PRIMARY KEY,
                        name nvarchar(260) NOT NULL,
                        checksum char(64) NOT NULL,
                        applied_at_utc datetime2(3) NOT NULL CONSTRAINT DF_schema_migrations_applied DEFAULT SYSUTCDATETIME()
                    );
                END;
            """)
            cursor.execute("SELECT checksum FROM app.schema_migrations WHERE migration_id=%s", (migration_path.stem,))
            existing = cursor.fetchone()
            if existing:
                if str(existing[0]) != checksum:
                    print("Migration checksum mismatch; refusing to run modified migration.")
                    return 1
                print(f"Migration already applied: {migration_path.name}")
                return 0
            for batch in split_batches(sql):
                cursor.execute(batch)
                while cursor.nextset():
                    pass
            cursor.execute(
                "INSERT INTO app.schema_migrations(migration_id,name,checksum) VALUES(%s,%s,%s)",
                (migration_path.stem, migration_path.name, checksum),
            )
    except pymssql.Error as exc:
        detail = " ".join(str(item) for item in exc.args)
        for secret in (settings.sql_password, settings.sql_username, settings.sql_server):
            if secret:
                detail = detail.replace(secret, "[redacted]")
        print(f"Migration failed: {detail[:800]}")
        return 1

    print(f"Applied migration: {migration_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
