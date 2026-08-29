from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.model_pipeline import train_all_markets  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an audited material-change research retrain")
    parser.add_argument("--material-change", required=True,
                        help="Versioned feature/label/regime/model/entry/exit/cost change identifier")
    arguments = parser.parse_args()
    print(json.dumps(train_all_markets(
        get_settings(), retrain_type="RESEARCH_RETRAIN",
        material_change=arguments.material_change,
    ), indent=2, default=str))
