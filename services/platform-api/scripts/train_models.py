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
    parser = argparse.ArgumentParser(description="Chronologically train and validate M15 models")
    parser.add_argument("--minimum-rows", type=int, default=2000)
    parser.add_argument("--minimum-auc", type=float, default=0.52)
    args = parser.parse_args()
    if args.minimum_rows < 2000:
        parser.error("--minimum-rows cannot be below the 2,000-row promotion evidence floor")
    if not 0.5 <= args.minimum_auc <= 0.9:
        parser.error("--minimum-auc must be between 0.5 and 0.9")
    print(json.dumps(train_all_markets(get_settings(), minimum_rows=args.minimum_rows,
                                       acceptance_auc=args.minimum_auc), indent=2))
