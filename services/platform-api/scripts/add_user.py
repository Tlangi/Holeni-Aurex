"""Add a user to the existing owner tenant without setting a password."""

import argparse
from pathlib import Path
import sys
from uuid import uuid4

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.config import get_settings
from app.database import open_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=("owner", "administrator", "viewer"), default="owner")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email or len(email) > 320:
        print("A valid email address is required.")
        return 2

    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc;")
        tenant = cursor.fetchone()
        if not tenant:
            print("No tenant exists.")
            return 1
        tenant_id = str(tenant[0])
        cursor.execute(
            "SELECT user_id, status FROM app.users WHERE tenant_id=%s AND LOWER(email)=LOWER(%s);",
            (tenant_id, email),
        )
        existing = cursor.fetchone()
        if existing:
            print(f"Account already exists with status: {existing[1]}")
            return 0

        user_id = str(uuid4())
        correlation_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO app.users
                (user_id, tenant_id, email, display_name, role, status)
            VALUES (%s, %s, %s, %s, %s, 'pending');
            """,
            (user_id, tenant_id, email, args.display_name.strip(), args.role),
        )
        cursor.execute(
            """
            INSERT INTO app.audit_logs
                (tenant_id, action_code, entity_type, entity_id,
                 correlation_id, metadata_json)
            VALUES (%s, 'user.created', 'user', %s, %s,
                    N'{"source":"owner_request"}');
            """,
            (tenant_id, user_id, correlation_id),
        )
        cursor.execute(
            "SELECT COUNT(1) FROM app.trading_accounts WHERE tenant_id=%s;",
            (tenant_id,),
        )
        linked_accounts = int(cursor.fetchone()[0])
        connection.commit()

    print("Account created in pending state.")
    print(f"Role: {args.role}")
    print(f"Linked tenant trading accounts: {linked_accounts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
