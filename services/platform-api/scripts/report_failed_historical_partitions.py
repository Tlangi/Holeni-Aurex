from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.historical_failure_triage import build_failed_partition_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze read-only triage for failed historical partitions")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite immutable report: {args.output}")
    report = build_failed_partition_report(get_settings())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "failed_partition_count", "reason_counts", "market_counts",
        "partition_set_sha256", "training_gate_effect")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
