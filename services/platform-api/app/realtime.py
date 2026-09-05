from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock

from fastapi import WebSocket, WebSocketDisconnect

from app.auth import authenticate_session_token
from app.config import Settings
from app.database import open_database
from app.research_jobs import read_research_jobs

ALLOWED_TIMEFRAMES = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
MAX_CONNECTIONS_PER_USER = 4
_connections: Counter[str] = Counter()
_connection_lock = Lock()


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _allowed_origin(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    return bool(origin and origin in settings.allowed_origins)


def _reserve(user_id: str) -> bool:
    with _connection_lock:
        if _connections[user_id] >= MAX_CONNECTIONS_PER_USER:
            return False
        _connections[user_id] += 1
        return True


def _release(user_id: str) -> None:
    with _connection_lock:
        _connections[user_id] = max(0, _connections[user_id] - 1)


def _bucket(opened: datetime, timeframe: str) -> datetime:
    value = opened.replace(tzinfo=timezone.utc)
    if timeframe == "D1":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = ALLOWED_TIMEFRAMES[timeframe]
    minute_of_day = value.hour * 60 + value.minute
    bucket_minute = minute_of_day - minute_of_day % minutes
    return value.replace(hour=bucket_minute // 60, minute=bucket_minute % 60, second=0, microsecond=0)


def read_live_candle(settings: Settings, tenant_id: str, symbol: str, timeframe: str) -> dict[str, object] | None:
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise ValueError("Unsupported timeframe")
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT 1 AS allowed FROM app.trading_accounts WHERE tenant_id=%s", (tenant_id,))
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1 AND research_enabled=1", (symbol,))
        allowed_market = cursor.fetchone()
        if not allowed_market:
            raise ValueError("Unsupported market")
        cursor.execute(
            """SELECT m.market_id,s.open_time_utc,s.[open],s.high,s.low,s.[close],s.bid_close,
                      s.ask_close,s.spread_close,s.tick_count,s.source_event_utc,s.source_sequence,
                      s.completed,s.updated_at_utc
               FROM app.markets m JOIN app.live_candle_snapshots s ON s.market_id=m.market_id
               WHERE m.symbol=%s AND m.enabled=1 AND m.research_enabled=1 AND s.timeframe='M5'""",
            (symbol,),
        )
        live = cursor.fetchone()
        if not live:
            return None
        start = _bucket(live["open_time_utc"], timeframe)
        if timeframe == "M5":
            rows = []
        else:
            cursor.execute(
                """SELECT [open],high,low,[close],bid_close,ask_close,spread_close,tick_count,open_time_utc
                   FROM app.candles WHERE market_id=%s AND timeframe='M5' AND completed=1
                     AND quality_status='PASS' AND open_time_utc>=%s AND open_time_utc<%s
                   ORDER BY open_time_utc""",
                (live["market_id"], start, live["open_time_utc"]),
            )
            rows = cursor.fetchall()
    values = rows + [live]
    first, last = values[0], values[-1]
    return {
        "type": "candle", "symbol": symbol, "timeframe": timeframe,
        "source_sequence": int(live["source_sequence"]),
        "source_event_utc": _iso(live["source_event_utc"]),
        "streamed_at_utc": datetime.now(timezone.utc).isoformat(),
        "candle": {
            "open_time_utc": start.isoformat(), "open_time_sast": start.isoformat(),
            "open": str(first["open"]), "high": str(max(Decimal(str(row["high"])) for row in values)),
            "low": str(min(Decimal(str(row["low"])) for row in values)), "close": str(last["close"]),
            "bid_close": str(last["bid_close"]) if last["bid_close"] is not None else None,
            "ask_close": str(last["ask_close"]) if last["ask_close"] is not None else None,
            "spread_close": str(last["spread_close"]) if last["spread_close"] is not None else None,
            "is_regular_session": True, "tick_count": sum(int(row["tick_count"] or 0) for row in values),
            "source": "IG_LIGHTSTREAMER_LIVE", "completed": bool(live["completed"]),
        },
    }


async def market_websocket(websocket: WebSocket, settings: Settings) -> None:
    symbol = (websocket.query_params.get("market") or "").upper()
    timeframe = (websocket.query_params.get("timeframe") or "").upper()
    token = websocket.cookies.get(settings.session_cookie_name)
    user = authenticate_session_token(token, settings)
    if not user or not _allowed_origin(websocket, settings):
        await websocket.close(code=1008)
        return
    if timeframe not in ALLOWED_TIMEFRAMES:
        await websocket.close(code=1008)
        return
    try:
        # Authorize the market before accepting the upgrade.
        snapshot = read_live_candle(settings, user.tenant_id, symbol, timeframe)
    except (ValueError, PermissionError):
        await websocket.close(code=1008)
        return
    if not _reserve(user.user_id):
        await websocket.close(code=1013)
        return
    await websocket.accept()
    last_sequence = -1
    idle_polls = 0
    try:
        while True:
            snapshot = await asyncio.to_thread(read_live_candle, settings, user.tenant_id, symbol, timeframe)
            sequence = int(snapshot["source_sequence"]) if snapshot else -1
            if snapshot and sequence != last_sequence:
                await websocket.send_json(snapshot)
                last_sequence = sequence
                idle_polls = 0
            else:
                idle_polls += 1
            if idle_polls and idle_polls % 15 == 0:
                await websocket.send_json({"type": "heartbeat", "sent_at_utc": datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _release(user.user_id)


async def training_websocket(websocket: WebSocket, settings: Settings) -> None:
    """Push persisted training state changes over the authenticated session."""
    user = authenticate_session_token(websocket.cookies.get(settings.session_cookie_name), settings)
    if not user or not _allowed_origin(websocket, settings):
        await websocket.close(code=1008)
        return
    if not _reserve(user.user_id):
        await websocket.close(code=1013)
        return
    await websocket.accept()
    previous = ""
    idle_polls = 0
    try:
        while True:
            payload = await asyncio.to_thread(read_research_jobs, settings, user.tenant_id, 20)
            marker = repr(payload)
            if marker != previous:
                await websocket.send_json({"type": "training_status", "data": payload})
                previous = marker
                idle_polls = 0
            else:
                idle_polls += 1
            if idle_polls and idle_polls % 8 == 0:
                await websocket.send_json({"type": "heartbeat", "sent_at_utc": datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _release(user.user_id)
