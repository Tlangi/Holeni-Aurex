import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import WebSocketDisconnect

from app.auth import AuthenticatedUser
from app.config import Settings
from app.markets import calculate_history_quality
from app.realtime import _bucket, market_websocket


def row(at: str) -> dict[str, object]:
    opened = datetime.fromisoformat(at.replace("Z", "+00:00")).replace(tzinfo=None)
    return {"open_time_utc": opened, "open": 1, "high": 2, "low": 0.5, "close": 1.5,
            "bid_close": 1.4, "ask_close": 1.6, "spread_close": .2, "tick_count": 1}


def fx_market() -> dict[str, object]:
    return {"asset_class": "FX", "calendar_code": "FX_24X5", "market_timezone": "UTC",
            "session_open_local": None, "session_close_local": None}


def test_live_candle_bucket_construction_for_every_supported_scale() -> None:
    value = datetime(2026, 9, 4, 18, 37, tzinfo=timezone.utc)
    assert _bucket(value, "M5").minute == 35
    assert _bucket(value, "M15").minute == 30
    assert _bucket(value, "M30").minute == 30
    assert (_bucket(value, "H1").hour, _bucket(value, "H1").minute) == (18, 0)
    assert _bucket(value, "H4").hour == 16
    assert (_bucket(value, "D1").hour, _bucket(value, "D1").minute) == (0, 0)


def test_quality_detects_expected_internal_fx_gap() -> None:
    quality = calculate_history_quality(
        [row("2026-09-04T18:00:00Z"), row("2026-09-04T18:10:00Z")], timeframe="M5",
        requested_start=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
        requested_end=datetime(2026, 9, 4, 18, 10, tzinfo=timezone.utc),
        market=fx_market(), holidays=set(), period="7D",
    )
    assert quality["quality_status"] == "INCOMPLETE"
    assert quality["missing_candle_count"] == 1
    assert quality["gap_count"] == 1
    assert quality["is_complete"] is False


def test_quality_excludes_fx_weekend_closure() -> None:
    quality = calculate_history_quality(
        [row("2026-09-04T20:55:00Z"), row("2026-09-07T00:00:00Z")], timeframe="M5",
        requested_start=datetime(2026, 9, 4, 20, 55, tzinfo=timezone.utc),
        requested_end=datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc),
        market=fx_market(), holidays=set(), period="7D",
    )
    assert quality["missing_candle_count"] == 0
    assert quality["is_complete"] is True


def test_unknown_calendar_never_claims_complete() -> None:
    market = {"asset_class": "METAL", "calendar_code": "FX_24X5", "market_timezone": "UTC",
              "session_open_local": None, "session_close_local": None}
    quality = calculate_history_quality(
        [row("2026-09-04T18:00:00Z")], timeframe="M5",
        requested_start=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
        requested_end=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
        market=market, holidays=set(), period="7D",
    )
    assert quality["quality_status"] == "UNVERIFIED"
    assert quality["completeness_percentage"] is None
    assert quality["is_complete"] is None


class FakeSocket:
    def __init__(self, *, cookie: bool = True) -> None:
        self.headers = {"origin": "http://testserver"}
        self.cookies = {"aurex_session": "x"} if cookie else {}
        self.query_params = {"market": "EURUSD", "timeframe": "M5"}
        self.accepted = False
        self.closed: int | None = None
        self.messages: list[dict[str, object]] = []
    async def accept(self) -> None: self.accepted = True
    async def close(self, code: int) -> None: self.closed = code
    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)
        raise WebSocketDisconnect()


def test_market_websocket_rejects_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, web_origins="http://testserver")
    monkeypatch.setattr("app.realtime.authenticate_session_token", lambda *_: None)
    socket = FakeSocket(cookie=False)
    asyncio.run(market_websocket(socket, settings))  # type: ignore[arg-type]
    assert socket.closed == 1008 and not socket.accepted


def test_market_websocket_pushes_authorized_read_only_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, web_origins="http://testserver")
    user = AuthenticatedUser("u1", "t1", "a@example.com", "A", "owner")
    monkeypatch.setattr("app.realtime.authenticate_session_token", lambda *_: user)
    monkeypatch.setattr("app.realtime.read_live_candle", lambda *_: {
        "type": "candle", "symbol": "EURUSD", "timeframe": "M5", "source_sequence": 1,
        "candle": {"open_time_utc": "2026-09-04T18:00:00+00:00"},
    })
    socket = FakeSocket()
    asyncio.run(market_websocket(socket, settings))  # type: ignore[arg-type]
    assert socket.accepted and socket.messages[0]["type"] == "candle"
