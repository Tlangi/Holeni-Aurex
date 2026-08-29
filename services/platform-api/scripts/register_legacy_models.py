"""Register trusted local model artifacts without claiming they are validated."""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402

EXPECTED_FEATURES = ["ret1", "ret4", "ema_gap", "rsi", "atr_pct", "range_pct", "volume_z"]
MODEL_DIR = ROOT / "ig-ai-forex-bot" / "models"


def artifact_metadata(path: Path) -> tuple[str, int]:
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or list(bundle.get("features") or []) != EXPECTED_FEATURES:
        raise ValueError(f"Unexpected model bundle features: {path.name}")
    horizon = int(bundle.get("horizon") or 0)
    if horizon <= 0 or not hasattr(bundle.get("model"), "predict_proba"):
        raise ValueError(f"Invalid model bundle: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest(), horizon


def register() -> None:
    artifacts = {symbol: MODEL_DIR / f"{symbol}.joblib" for symbol in ("EURUSD", "GBPUSD", "USDJPY")}
    metadata = {symbol: artifact_metadata(path) for symbol, path in artifacts.items()}
    settings = get_settings()

    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        try:
            cursor.execute("SELECT strategy_id FROM app.strategies WHERE strategy_name=%s", ("Conservative FX Demo",))
            row = cursor.fetchone()
            strategy_id = str(row["strategy_id"]) if row else str(uuid.uuid4())
            if not row:
                cursor.execute(
                    "INSERT app.strategies(strategy_id,strategy_name,environment,status) VALUES(%s,%s,'DEMO','ACTIVE')",
                    (strategy_id, "Conservative FX Demo"),
                )

            cursor.execute(
                "SELECT strategy_version_id FROM app.strategy_versions WHERE strategy_id=%s AND version='1.0'",
                (strategy_id,),
            )
            row = cursor.fetchone()
            strategy_version_id = str(row["strategy_version_id"]) if row else str(uuid.uuid4())
            if not row:
                cursor.execute(
                    """INSERT app.strategy_versions
                       (strategy_version_id,strategy_id,version,timeframe,buy_threshold,sell_threshold,features_version)
                       VALUES(%s,%s,'1.0','M15',0.58,0.42,'legacy-v1')""",
                    (strategy_version_id, strategy_id),
                )

            for symbol, path in artifacts.items():
                digest, _ = metadata[symbol]
                cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s", (symbol,))
                market = cursor.fetchone()
                if not market:
                    raise RuntimeError(f"Market is not provisioned: {symbol}")
                cursor.execute(
                    """SELECT model_version_id FROM app.model_versions
                       WHERE strategy_version_id=%s AND market_id=%s AND version='legacy-1'""",
                    (strategy_version_id, str(market["market_id"])),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """UPDATE app.model_versions SET artifact_path=%s,artifact_sha256=%s,
                           status='REGISTERED',validation_auc=NULL,training_rows=NULL
                           WHERE model_version_id=%s""",
                        (str(path.resolve()), digest, str(existing["model_version_id"])),
                    )
                else:
                    cursor.execute(
                        """INSERT app.model_versions
                           (model_version_id,strategy_version_id,market_id,model_name,version,
                            artifact_path,artifact_sha256,status)
                           VALUES(%s,%s,%s,%s,'legacy-1',%s,%s,'REGISTERED')""",
                        (
                            str(uuid.uuid4()), strategy_version_id, str(market["market_id"]),
                            f"{symbol} HistGradientBoosting", str(path.resolve()), digest,
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    print("Registered 3 local models with status REGISTERED (not yet validated).")


if __name__ == "__main__":
    register()
