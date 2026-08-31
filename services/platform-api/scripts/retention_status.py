from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database import open_database


QUERIES = {
    "CANDLES": "SELECT COUNT(1) count FROM app.candles WHERE open_time_utc<DATEADD(day,-%s,SYSUTCDATETIME())",
    "AUDIT_LOGS": "SELECT COUNT(1) count FROM app.audit_logs WHERE occurred_at_utc<DATEADD(day,-%s,SYSUTCDATETIME())",
    "RESEARCH_EXPERIMENTS": "SELECT COUNT(1) count FROM app.research_experiments WHERE started_at_utc<DATEADD(day,-%s,SYSUTCDATETIME())",
    "AUTH_ATTEMPTS": "SELECT COUNT(1) count FROM app.authentication_attempts WHERE attempted_at_utc<DATEADD(day,-%s,SYSUTCDATETIME())",
    "QUARANTINE": "SELECT COUNT(1) count FROM app.market_data_quarantine WHERE observed_at_utc<DATEADD(day,-%s,SYSUTCDATETIME())",
}


def main() -> None:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT entity_code,hot_retention_days,archive_required,policy_json FROM app.data_retention_policies WHERE enabled=1 ORDER BY entity_code")
        for policy in cursor.fetchall():
            cursor.execute(QUERIES[str(policy["entity_code"])], (int(policy["hot_retention_days"]),))
            count = int(cursor.fetchone()["count"])
            print(f"{policy['entity_code']}: eligible={count}; archive_required={bool(policy['archive_required'])}; action=NONE_DRY_RUN")


if __name__ == "__main__":
    main()
