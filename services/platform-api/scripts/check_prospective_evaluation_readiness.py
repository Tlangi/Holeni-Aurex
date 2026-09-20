"""Read-only future-window gate; never opens labels or runs inference."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_evaluation_readiness import evaluation_readiness
from scripts.freeze_selected_prospective_models import MANIFEST, ROOT
from scripts.verify_selected_prospective_models import main as verify_models


WINDOWS = ROOT / "docs/research/AUREX_PROSPECTIVE_EVALUATION_WINDOWS_V1.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("validation", "holdout"), required=True)
    args = parser.parse_args()
    verify_models()
    windows = json.loads(WINDOWS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if windows["selected_model_manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError("Evaluation windows are not bound to frozen selected models")
    # No validation report verifier exists yet, so the CLI keeps holdout closed
    # even after its calendar window completes. A later implementation must
    # verify report provenance and each market's pass state before changing this.
    result = evaluation_readiness(windows, phase=args.phase,
        now_utc=datetime.now(timezone.utc), validation_report_frozen=False)
    print(json.dumps(result, indent=2))
    if result["status"] == "BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
