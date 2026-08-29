from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.dukascopy_import import import_directory, import_file  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idempotently import Dukascopy bid M5 CSV history")
    parser.add_argument("--directory", type=Path, default=PROJECT_ROOT / "dukascopy" / "download")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    settings = get_settings()
    result = (
        {arguments.file.name: import_file(settings, arguments.file, batch_size=arguments.batch_size,
                                          dry_run=arguments.dry_run)}
        if arguments.file else
        import_directory(settings, arguments.directory, batch_size=arguments.batch_size,
                         dry_run=arguments.dry_run)
    )
    print(json.dumps(result, indent=2, default=str))
