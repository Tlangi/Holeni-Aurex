from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal
from uuid import uuid4

from app.execution_simulator import resolve_candle_exit, transaction_cost_evidence


@dataclass(frozen=True)
class ShadowExit:
    closed: bool
    price: Decimal
    reason: str | None


def resolve_shadow_candle(
    direction: str, *, stop: Decimal, target: Decimal, high: Decimal, low: Decimal, close: Decimal,
) -> ShadowExit:
    """Resolve one completed candle conservatively when intrabar ordering is unknown."""
    result = resolve_candle_exit(
        direction, stop=stop, target=target, opened=close, high=high, low=low,
        close=close, holding_candles=0, max_holding_candles=2**31-1,
    )
    return ShadowExit(result.closed, result.price, result.reason)


def shadow_pnl(
    direction: str, *, entry: Decimal, current: Decimal, size: Decimal,
    value_per_price_point_zar: Decimal, estimated_cost_zar: Decimal,
) -> Decimal:
    sign = Decimal("1") if direction == "BUY" else Decimal("-1")
    return (current - entry) * sign * size * value_per_price_point_zar - estimated_cost_zar


def open_shadow_trade(
    cursor: object, *, tenant_id: str, intent_id: str, market_id: str, direction: str,
    size: Decimal, entry: Decimal, stop: Decimal, target: Decimal, candle_id: int,
    opened_at: object, value_per_price_point_zar: Decimal, cost_bps: Decimal,
    bid: Decimal | None = None, ask: Decimal | None = None,
) -> str:
    shadow_id = str(uuid4())
    cost = transaction_cost_evidence(
        midpoint=entry, bid=bid, ask=ask, size=size,
        value_per_price_point_zar=value_per_price_point_zar,
        fallback_round_trip_cost_bps=cost_bps,
    )
    estimated_cost = cost.explicit_cost_zar
    cursor.execute(
        """IF NOT EXISTS(SELECT 1 FROM app.shadow_trades WHERE order_intent_id=%s)
           BEGIN INSERT app.shadow_trades
             (shadow_trade_id,tenant_id,order_intent_id,market_id,direction,size,entry_price,
              stop_price,target_price,value_per_price_point_zar,estimated_entry_cost_zar,current_price,
              unrealized_pnl_zar,status,entry_candle_id,last_candle_id,opened_at_utc,entry_spread_zar,
              spread_cost_in_price)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'OPEN',%s,%s,%s,%s,%s)
           INSERT app.shadow_trade_events(shadow_trade_id,event_type,candle_id,price,pnl_zar,details_json,occurred_at_utc)
           VALUES(%s,'OPENED',%s,%s,%s,%s,%s) END""",
        (intent_id, shadow_id, tenant_id, intent_id, market_id, direction, size, entry, stop, target,
         value_per_price_point_zar, estimated_cost, entry, -estimated_cost, candle_id, candle_id, opened_at,
         cost.spread_cost_zar, cost.spread_cost_in_price,
         shadow_id, candle_id, entry, -estimated_cost,
         json.dumps({"environment": "SHADOW", "estimated_round_trip_cost_bps": str(cost_bps),
                     "spread_cost_in_executable_prices": cost.spread_cost_in_price}), opened_at),
    )
    return shadow_id


def mark_shadow_trades(cursor: object, tenant_id: str) -> list[dict[str, object]]:
    cursor.execute("SELECT * FROM app.shadow_trades WHERE tenant_id=%s AND status='OPEN'", (tenant_id,))
    outcomes: list[dict[str, object]] = []
    for trade in cursor.fetchall():
        cursor.execute(
            """SELECT candle_id,open_time_utc,[open],high,low,[close],bid_open,bid_high,bid_low,bid_close,
                      ask_open,ask_high,ask_low,ask_close FROM app.candles
               WHERE market_id=%s AND timeframe='M15' AND completed=1 AND quality_status='PASS'
                 AND candle_id>%s ORDER BY open_time_utc""",
            (str(trade["market_id"]), int(trade["last_candle_id"])),
        )
        for candle in cursor.fetchall():
            side = "bid" if str(trade["direction"]) == "BUY" else "ask"
            value = lambda name: Decimal(str(candle[f"{side}_{name}"] if candle[f"{side}_{name}"] is not None else candle[name if name != "close" else "close"]))
            resolved = resolve_candle_exit(
                str(trade["direction"]), stop=Decimal(str(trade["stop_price"])),
                target=Decimal(str(trade["target_price"])), opened=value("open"),
                high=value("high"), low=value("low"), close=value("close"),
                holding_candles=int(trade["holding_candles"] or 0)+1,
                max_holding_candles=int(trade["max_holding_candles"] or 32),
            )
            exit_result = ShadowExit(resolved.closed, resolved.price, resolved.reason)
            pnl = shadow_pnl(
                str(trade["direction"]), entry=Decimal(str(trade["entry_price"])),
                current=exit_result.price, size=Decimal(str(trade["size"])),
                value_per_price_point_zar=Decimal(str(trade["value_per_price_point_zar"])),
                estimated_cost_zar=Decimal(str(trade["estimated_entry_cost_zar"])),
            )
            occurred = candle["open_time_utc"].replace(tzinfo=timezone.utc)
            if exit_result.closed:
                cursor.execute(
                    """UPDATE app.shadow_trades SET current_price=%s,unrealized_pnl_zar=0,
                       exit_price=%s,realized_pnl_zar=%s,exit_reason=%s,status='CLOSED',last_candle_id=%s,
                       holding_candles=holding_candles+1,closed_at_utc=%s,updated_at_utc=SYSUTCDATETIME()
                       WHERE shadow_trade_id=%s AND status='OPEN'""",
                    (exit_result.price, exit_result.price, pnl, exit_result.reason, candle["candle_id"],
                     occurred, str(trade["shadow_trade_id"])),
                )
                event = "STOPPED" if str(exit_result.reason).startswith("STOP") else "TARGET_HIT" if exit_result.reason == "TAKE_PROFIT" else "TIME_EXIT"
            else:
                cursor.execute(
                    """UPDATE app.shadow_trades SET current_price=%s,unrealized_pnl_zar=%s,last_candle_id=%s,
                       holding_candles=holding_candles+1,
                       updated_at_utc=SYSUTCDATETIME() WHERE shadow_trade_id=%s AND status='OPEN'""",
                    (exit_result.price, pnl, candle["candle_id"], str(trade["shadow_trade_id"])),
                )
                event = "MARKED"
            cursor.execute(
                """INSERT app.shadow_trade_events(shadow_trade_id,event_type,candle_id,price,pnl_zar,
                   details_json,occurred_at_utc) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (str(trade["shadow_trade_id"]), event, candle["candle_id"], exit_result.price, pnl,
                 json.dumps({"exit_reason": exit_result.reason}), occurred),
            )
            outcomes.append({"shadow_trade_id": str(trade["shadow_trade_id"]), "event": event,
                             "pnl_zar": str(pnl)})
            if exit_result.closed:
                break
    return outcomes
