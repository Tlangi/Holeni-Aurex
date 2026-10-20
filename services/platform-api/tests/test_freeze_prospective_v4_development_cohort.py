from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from scripts.freeze_prospective_v4_development_cohort import require_ready


ROOT = Path(__file__).resolve().parents[3]


def protocol() -> dict[str, object]:
    return json.loads((ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V4.json")
                      .read_text(encoding="utf-8"))


def test_v4_development_freeze_is_blocked_before_horizon() -> None:
    with pytest.raises(RuntimeError, match="V4_DEVELOPMENT_WINDOW_NOT_COMPLETE"):
        require_ready(protocol(), now=datetime(2026, 10, 27, 19, 29, tzinfo=timezone.utc))


def test_v4_development_freeze_opens_at_horizon() -> None:
    require_ready(protocol(), now=datetime(2026, 10, 27, 19, 30, tzinfo=timezone.utc))
