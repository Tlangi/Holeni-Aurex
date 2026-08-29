from __future__ import annotations

from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

FEATURES = ["ret1", "ret4", "ema_gap", "rsi", "atr_pct", "range_pct", "volume_z"]


def add_features(df: pd.DataFrame, horizon: int = 4, labelled: bool = True) -> pd.DataFrame:
    x = df.copy()
    close, high, low = x.close, x.high, x.low
    x["ret1"] = close.pct_change()
    x["ret4"] = close.pct_change(4)
    x["ema_gap"] = close.ewm(span=12).mean() / close.ewm(span=26).mean() - 1
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0.0)
    x["rsi"] = rsi.mask((gain == 0) & (loss == 0), 50.0)
    previous = close.shift(1)
    tr = pd.concat([(high-low), (high-previous).abs(), (low-previous).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean()
    x["atr_pct"] = x.atr / close
    x["range_pct"] = (high-low) / close
    volume = x.tick_volume.astype(float)
    volume_std = volume.rolling(50).std()
    x["volume_z"] = ((volume-volume.rolling(50).mean()) / volume_std.replace(0, np.nan)).fillna(0.0)
    if labelled:
        future_close = close.shift(-horizon)
        x["target"] = np.where(future_close.notna(), (future_close > close).astype(float), np.nan)
    return x.replace([np.inf, -np.inf], np.nan).dropna()


def train(df: pd.DataFrame, horizon: int, model_path: str, minimum_rows: int = 2000,
          minimum_auc: float = 0.52) -> dict:
    data = add_features(df, horizon, labelled=True)
    split = int(len(data) * 0.8)
    if len(data) < minimum_rows or split < 500 or len(data) - split < 100:
        raise ValueError("Not enough chronological data to train and validate")
    train_set, test_set = data.iloc[:split], data.iloc[split:]
    model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                           l2_regularization=1.0, random_state=42)
    model.fit(train_set[FEATURES], train_set.target.astype(int))
    probability = model.predict_proba(test_set[FEATURES])[:, 1]
    auc = roc_auc_score(test_set.target.astype(int), probability)
    if auc < minimum_auc:
        raise ValueError(f"Validation AUC {auc:.4f} is below required {minimum_auc:.4f}; model not saved")
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES, "horizon": horizon}, model_path)
    return {"rows": len(data), "validation_rows": len(test_set), "validation_auc": round(float(auc), 4)}


def predict(df: pd.DataFrame, model_path: str) -> tuple[float, float]:
    bundle = joblib.load(model_path)
    row = add_features(df, bundle["horizon"], labelled=False).iloc[-1]
    probability = float(bundle["model"].predict_proba(row[bundle["features"]].to_frame().T)[0, 1])
    return probability, float(row.atr)
