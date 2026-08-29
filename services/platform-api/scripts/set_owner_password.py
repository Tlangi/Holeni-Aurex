"""Set the owner password interactively without placing it in shell history."""

from getpass import getpass
import argparse
from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.auth import hash_password
from app.config import get_settings
from app.database import open_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Set an Aurex user password")
    parser.add_argument("--email", required=True, help="Exact user email address")
    args = parser.parse_args()
    email = args.email.strip().lower()

    first = getpass("New owner password: ")
    second = getpass("Confirm owner password: ")
    if first != second:
        print("Passwords do not match.")
        return 2
    try:
        encoded = hash_password(first)
    except ValueError as exc:
        print(str(exc))
        return 2

    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT user_id FROM app.users WHERE LOWER(email)=LOWER(%s);", (email,)
        )
        row = cursor.fetchone()
        if not row:
            print("No user exists with that email address.")
            return 1
        cursor.execute(
            "UPDATE app.users SET password_hash=%s, status='active', updated_at_utc=SYSUTCDATETIME() WHERE user_id=%s;",
            (encoded, str(row[0])),
        )
        cursor.execute(
            "UPDATE app.auth_sessions SET revoked_at_utc=SYSUTCDATETIME() WHERE user_id=%s AND revoked_at_utc IS NULL;",
            (str(row[0]),),
        )
        connection.commit()
    print("User password updated, account activated, and existing sessions revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
