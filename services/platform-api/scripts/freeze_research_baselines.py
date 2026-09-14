"""Print read-only GBPUSD/USDJPY baseline manifests; redirect only via approved artifact workflow."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.research_baselines import freeze_existing_baselines  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(freeze_existing_baselines(get_settings()), indent=2, default=str))
