from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=settings.api_host, port=settings.api_port,
        reload=False, access_log=False, log_level="warning",
    )
