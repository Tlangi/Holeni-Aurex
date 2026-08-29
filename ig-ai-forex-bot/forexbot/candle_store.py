from __future__ import annotations

from pathlib import Path
import os
import threading

import pandas as pd


COLUMNS = ["record_type", "timeframe", "time", "open", "high", "low", "close", "tick_volume"]
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class CandleStore:
    """Durable, atomic CSV candle storage: one file per configured symbol."""

    def __init__(self, path: str = "data/candles", symbols=()):
        candidate = Path(path)
        self.directory = candidate.parent / "candles" if candidate.suffix else candidate
        self.directory.mkdir(parents=True, exist_ok=True)
        for symbol in symbols:
            self._ensure(symbol)

    def file_path(self, symbol: str) -> Path:
        if not symbol or not symbol.replace("_", "").isalnum():
            raise ValueError(f"Invalid candle symbol: {symbol!r}")
        return self.directory / f"{symbol.upper()}.csv"

    def put(self, symbol: str, timeframe: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        incoming = frame.copy()
        incoming["record_type"] = "candle"
        incoming["timeframe"] = timeframe
        incoming["time"] = pd.to_datetime(incoming["time"], utc=True).map(lambda value: value.isoformat())
        incoming = incoming[COLUMNS]
        path, lock = self.file_path(symbol), self._lock(symbol)
        with lock:
            current = self._read(path)
            combined = pd.concat([current, incoming], ignore_index=True)
            candles = combined.record_type.eq("candle")
            candle_rows = combined[candles].drop_duplicates(["timeframe", "time"], keep="last")
            metadata = combined[~candles].drop_duplicates(["record_type", "timeframe"], keep="last")
            self._write_atomic(path, pd.concat([metadata, candle_rows], ignore_index=True))

    def get(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        path, lock = self.file_path(symbol), self._lock(symbol)
        with lock:
            frame = self._read(path)
        selected = frame[(frame.record_type == "candle") & (frame.timeframe == timeframe)].copy()
        columns = ["time", "open", "high", "low", "close", "tick_volume"]
        if selected.empty:
            return pd.DataFrame(columns=columns)
        selected["time"] = pd.to_datetime(selected.time, utc=True)
        for column in columns[1:]:
            selected[column] = pd.to_numeric(selected[column], errors="coerce")
        return selected.sort_values("time").tail(count)[columns].reset_index(drop=True)

    def count(self, symbol: str, timeframe: str) -> int:
        path, lock = self.file_path(symbol), self._lock(symbol)
        with lock:
            frame = self._read(path)
        return int(((frame.record_type == "candle") & (frame.timeframe == timeframe)).sum())

    def bounds(self, symbol: str, timeframe: str) -> tuple[str | None, str | None]:
        frame = self.get(symbol, timeframe, 10**9)
        if frame.empty:
            return None, None
        return frame.iloc[0].time.isoformat(), frame.iloc[-1].time.isoformat()

    def get_meta(self, key: str) -> str | None:
        symbol = self._symbol_from_meta_key(key)
        path, lock = self.file_path(symbol), self._lock(symbol)
        with lock:
            frame = self._read(path)
        row = frame[(frame.record_type == "metadata") & (frame.timeframe == key)]
        return str(row.iloc[-1].time) if not row.empty else None

    def set_meta(self, key: str, value: object) -> None:
        symbol = self._symbol_from_meta_key(key)
        path, lock = self.file_path(symbol), self._lock(symbol)
        row = pd.DataFrame([{
            "record_type": "metadata", "timeframe": key, "time": str(value),
            "open": "", "high": "", "low": "", "close": "", "tick_volume": "",
        }], columns=COLUMNS)
        with lock:
            current = self._read(path)
            current = current[~((current.record_type == "metadata") & (current.timeframe == key))]
            self._write_atomic(path, pd.concat([current, row], ignore_index=True))

    def _ensure(self, symbol: str) -> None:
        path, lock = self.file_path(symbol), self._lock(symbol)
        with lock:
            if not path.exists():
                self._write_atomic(path, pd.DataFrame(columns=COLUMNS))

    def _lock(self, symbol: str) -> threading.RLock:
        key = str(self.file_path(symbol).resolve())
        with _LOCKS_GUARD:
            return _LOCKS.setdefault(key, threading.RLock())

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame(columns=COLUMNS)
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        missing = set(COLUMNS) - set(frame.columns)
        if missing:
            raise RuntimeError(f"Invalid candle file {path}: missing columns {sorted(missing)}")
        return frame[COLUMNS]

    @staticmethod
    def _write_atomic(path: Path, frame: pd.DataFrame) -> None:
        temporary = path.with_suffix(".csv.tmp")
        frame.to_csv(temporary, index=False)
        os.replace(temporary, path)

    @staticmethod
    def _symbol_from_meta_key(key: str) -> str:
        parts = key.split(":")
        if len(parts) < 3 or parts[0] != "last_refresh":
            raise ValueError(f"Unsupported candle metadata key: {key}")
        return parts[1]
