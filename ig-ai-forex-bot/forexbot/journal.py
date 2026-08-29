from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trade_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
  volume REAL NOT NULL, price REAL NOT NULL, stop_loss REAL, take_profit REAL,
  probability REAL, ticket TEXT, status TEXT NOT NULL, message TEXT
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
  created_at TEXT PRIMARY KEY, balance REAL NOT NULL, equity REAL NOT NULL,
  margin REAL, free_margin REAL
);
"""


class Journal:
    def __init__(self, path: str = "data/trading.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def get(self, key: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: object) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def daily_start_equity(self, current_equity: float) -> float:
        today = date.today().isoformat()
        if self.get("equity_date") != today:
            self.set("equity_date", today)
            self.set("start_equity", current_equity)
        return float(self.get("start_equity") or current_equity)

    def mark_bar(self, symbol: str, bar_time: datetime) -> None:
        self.set(f"last_bar:{symbol}", bar_time.isoformat())

    def bar_processed(self, symbol: str, bar_time: datetime) -> bool:
        return self.get(f"last_bar:{symbol}") == bar_time.isoformat()

    def snapshot(self, account) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO equity_snapshots VALUES(?,?,?,?,?)", (
                now, float(account.balance), float(account.equity),
                float(account.margin), float(account.margin_free)))

    def record_trade(self, *, symbol: str, side: str, volume: float, price: float,
                     stop_loss: float, take_profit: float, probability: float,
                     ticket: str | None, status: str, message: str = "") -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO trade_events
                (created_at,symbol,side,volume,price,stop_loss,take_profit,probability,ticket,status,message)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                datetime.now(timezone.utc).isoformat(), symbol, side, volume, price,
                stop_loss, take_profit, probability, ticket, status, message))

    def trades(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM trade_events ORDER BY created_at")]

    def snapshots(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM equity_snapshots ORDER BY created_at")]
