"""Run only the owner-summary ASGI app on localhost; no platform lifespan."""
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

if __name__ == "__main__":
    uvicorn.run("app.owner_overview_api:app", host="127.0.0.1", port=8011,
                reload=False, access_log=False, log_level="warning")
