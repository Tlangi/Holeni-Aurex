"""Import only local Dukascopy gap-day evidence and derive safe M5 candles."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.dukascopy_tick_import import import_dukascopy_ticks  # noqa: E402
from app.historical_backfill import update_job  # noqa: E402
from app.historical_validation import validate_partition  # noqa: E402
from app.timeframe_fallback import persist_batch_cross_timeframe_recovery  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "dukascopy" / "backfill" / "daily")
    parser.add_argument("--dates", nargs="+", default=["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-11"])
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Restrict recovery to explicit market symbols (for example GBPUSD)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    selected: dict[tuple[str, str], Path] = {}
    wanted_dates = {value.replace("-", ""): value for value in args.dates}
    for path in args.root.rglob("*.csv.csv"):
        parts = path.name.lower().removesuffix(".csv.csv").rsplit("-", 1)
        if len(parts) != 2 or parts[1] not in wanted_dates or path.stat().st_size == 0:
            continue
        symbol = "GERMANY40" if parts[0].upper() == "DEUIDXEUR" else parts[0].upper()
        if args.symbols and symbol not in {value.upper() for value in args.symbols}:
            continue
        key = (symbol, wanted_dates[parts[1]])
        if key not in selected or path.stat().st_size > selected[key].stat().st_size:
            selected[key] = path
    print(f"selected_files={len(selected)}")
    for (symbol, day), path in sorted(selected.items()):
        start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        print(f"{symbol} {day} {path} bytes={path.stat().st_size}")
        if args.dry_run:
            continue
        vendor_symbol = "DEUIDXEUR" if symbol == "GERMANY40" else symbol
        result = import_dukascopy_ticks(get_settings(), symbol=symbol, path=path,
            vendor_symbol=vendor_symbol, requested_start=start, requested_end=end)
        batch = str(result["import_batch_id"])
        validation = validate_partition(get_settings(), batch)
        recovery = persist_batch_cross_timeframe_recovery(get_settings(), batch)
        print({"symbol": symbol, "day": day, "batch": batch,
               "import": result, "validation": validation, "recovery": recovery})


if __name__ == "__main__":
    main()
