from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.forward_evidence import capture_forward_evidence  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT tenant_id FROM app.engine_controls ORDER BY tenant_id")
        tenants = [str(row[0]) for row in cursor.fetchall()]
    result = {tenant: capture_forward_evidence(settings, tenant) for tenant in tenants}
    print(json.dumps(result, indent=2, default=str))
