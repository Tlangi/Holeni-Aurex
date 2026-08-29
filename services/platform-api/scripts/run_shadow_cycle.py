from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.shadow_engine import run_shadow_cycle  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP 1 tenant_id FROM app.tenants ORDER BY created_at_utc")
        row = cursor.fetchone()
    if not row:
        raise SystemExit("No tenant exists")
    print(json.dumps(run_shadow_cycle(settings, str(row[0])), indent=2))
