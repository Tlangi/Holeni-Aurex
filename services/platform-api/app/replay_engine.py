from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

import joblib
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.database import open_database
from app.execution_simulator import entry_price, resolve_candle_exit, transaction_cost_evidence
from app.model_pipeline import FEATURES, add_features


class ReplayRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    mode: str = Field(default="VALIDATED_MODEL", pattern="^(VALIDATED_MODEL|TECHNICAL_DIAGNOSTIC)$")
    initial_equity_zar: Decimal = Field(default=Decimal("100000"), ge=Decimal("1000"), le=Decimal("100000000"))
    max_candles: int = Field(default=2000, ge=60, le=100000)
    from_utc: datetime | None = Field(default=None, alias="from")
    to_utc: datetime | None = Field(default=None, alias="to")
    segment_mode: str = Field(default="CONTINUOUS_ONLY", pattern="^(CONTINUOUS_ONLY|LATEST_WINDOW)$")
    cost_mode: str = Field(default="NORMAL", pattern="^(OPTIMISTIC|NORMAL|STRESSED)$")
    use_latest_model: bool = False


@dataclass
class OpenReplayTrade:
    trade_id: str
    direction: str
    size: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal
    entry_candle_id: int
    opened_at: datetime
    spread_cost_zar: Decimal
    explicit_cost_zar: Decimal
    spread_cost_in_price: bool
    slippage_cost_zar: Decimal
    holding: int = 0


def _technical_score(row: pd.Series) -> float:
    atr = max(float(row["atr_pct"]), 1e-9)
    trend = max(-1.0, min(1.0, float(row["ema_gap"]) / atr))
    momentum = max(-1.0, min(1.0, float(row["ret4"]) / atr))
    rsi = max(-1.0, min(1.0, (float(row["rsi"]) - 50.0) / 50.0))
    return max(-1.0, min(1.0, trend * 0.45 + momentum * 0.35 + rsi * 0.20))


def _largest_continuous_segment(candles: list[dict[str, object]]) -> list[dict[str, object]]:
    if not candles:
        return candles
    segments: list[list[dict[str, object]]] = [[]]
    previous: datetime | None = None
    for candle in candles:
        opened = candle["open_time_utc"]
        if previous is not None and opened - previous != pd.Timedelta(15, unit="min"):
            segments.append([])
        segments[-1].append(candle)
        previous = opened
    return max(segments, key=len)


def run_replay(settings: Settings, tenant_id: str, request: ReplayRequest) -> dict[str, object]:
    symbol = request.symbol.upper()
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT market_id,symbol FROM app.markets WHERE symbol=%s AND enabled=1""", (symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError("Unsupported or disabled replay market")
        cursor.execute(
            """SELECT TOP (1) r.min_deal_size,r.size_increment,r.min_stop_distance,
                      r.value_per_price_point_zar
               FROM app.broker_market_rules r JOIN app.broker_connections b
                 ON b.broker_connection_id=r.broker_connection_id
               WHERE r.market_id=%s AND b.environment='demo' ORDER BY r.observed_at_utc DESC""",
            (str(market["market_id"]),),
        )
        rule = cursor.fetchone()
        if not rule:
            raise ValueError("Current broker rule is required for replay sizing")
        cursor.execute(
            """SELECT TOP (%s) candle_id,open_time_utc,[open],high,low,[close],
                      bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                      spread_close,tick_count,is_regular_session
               FROM app.candles WHERE market_id=%s AND timeframe='M15' AND completed=1
                 AND quality_status='PASS' AND is_regular_session=1
                 AND (%s IS NULL OR open_time_utc>=%s)
                 AND (%s IS NULL OR open_time_utc<=%s)
               ORDER BY open_time_utc DESC""",
            (request.max_candles, str(market["market_id"]), request.from_utc, request.from_utc,
             request.to_utc, request.to_utc),
        )
        candles = list(reversed(cursor.fetchall()))
        cursor.execute(
            """SELECT TOP (1) mv.model_version_id,mv.artifact_path,sv.strategy_version_id,
                      sv.buy_threshold,sv.sell_threshold
               FROM app.model_versions mv JOIN app.strategy_versions sv
                 ON sv.strategy_version_id=mv.strategy_version_id
               WHERE mv.market_id=%s AND mv.status='VALIDATED' ORDER BY mv.registered_at_utc DESC""",
            (str(market["market_id"]),),
        )
        model_record = cursor.fetchone()
        if request.mode == "TECHNICAL_DIAGNOSTIC" and request.use_latest_model:
            cursor.execute(
                """SELECT TOP (1) mv.model_version_id,mv.artifact_path,sv.strategy_version_id,
                          sv.buy_threshold,sv.sell_threshold
                   FROM app.model_versions mv JOIN app.strategy_versions sv
                     ON sv.strategy_version_id=mv.strategy_version_id
                   WHERE mv.market_id=%s AND mv.artifact_path IS NOT NULL
                   ORDER BY mv.registered_at_utc DESC""", (str(market["market_id"]),),
            )
            model_record = cursor.fetchone()
        cursor.execute(
            """SELECT TOP (1) c.cost_model_version_id,c.version,b.median_spread,b.p75_spread,b.p95_spread
               FROM app.cost_model_versions c JOIN app.cost_model_buckets b
                 ON b.cost_model_version_id=c.cost_model_version_id
               WHERE c.market_id=%s AND c.status='CURRENT' AND b.bucket_type='OVERALL'
               ORDER BY c.created_at_utc DESC""", (str(market["market_id"]),),
        )
        cost_model = cursor.fetchone()

    if len(candles) < 60:
        return _persist_empty(settings, tenant_id, market, request, candles, "INSUFFICIENT_CANDLES")
    if request.mode == "VALIDATED_MODEL" and not model_record:
        return _persist_empty(settings, tenant_id, market, request, candles, "MODEL_NOT_VALIDATED")

    frame = pd.DataFrame(candles)
    frame["time"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    frame = frame.set_index("time")
    frame["tick_volume"] = frame["tick_count"]
    for column in ("open", "high", "low", "close", "tick_volume"):
        frame[column] = pd.to_numeric(frame[column])
    feature_input = frame[["open", "high", "low", "close", "tick_volume"]]
    featured = add_features(feature_input, labelled=False).join(
        frame[["candle_id", "bid_open", "bid_high", "bid_low", "bid_close",
               "ask_open", "ask_high", "ask_low", "ask_close", "is_regular_session"]], how="left",
    )
    model = None
    if model_record:
        bundle = joblib.load(str(model_record["artifact_path"]))
        model = bundle["model"]
        featured["_model_probability"] = model.predict_proba(featured[FEATURES])[:, 1]

    config = {
        "replay_version": "UNIFIED_V3_REJECTED_MODEL_DIAGNOSTICS",
        "mode": request.mode, "initial_equity_zar": str(request.initial_equity_zar),
        "risk_per_trade_pct": "0.25", "reward_risk": "1.5", "max_holding_candles": 32,
        "technical_diagnostic_threshold": "0.15",
        "use_latest_model": request.use_latest_model,
        "segment_mode": request.segment_mode,
        "requested_from_utc": request.from_utc.isoformat() if request.from_utc else None,
        "requested_to_utc": request.to_utc.isoformat() if request.to_utc else None,
        "cost_mode": request.cost_mode,
        "cost_model_version": str(cost_model["version"]) if cost_model else "CONFIGURED_BPS_FALLBACK",
        "slippage_bps": str(settings.replay_slippage_bps), "funding_bps_per_day": str(settings.replay_funding_bps_per_day),
        "cost_evidence": "BID_ASK_WHERE_AVAILABLE",
    }
    digest = hashlib.sha256(json.dumps({"symbol": symbol, "first": str(candles[0]["open_time_utc"]),
        "last": str(candles[-1]["open_time_utc"]), **config}, sort_keys=True).encode()).hexdigest()
    run_id = str(uuid4())
    equity = Decimal(request.initial_equity_zar)
    peak = equity
    max_drawdown = Decimal("0")
    open_trade: OpenReplayTrade | None = None
    completed: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    value = Decimal(str(rule["value_per_price_point_zar"]))
    minimum = Decimal(str(rule["min_deal_size"]))
    increment = Decimal(str(rule["size_increment"]))
    min_stop = Decimal(str(rule["min_stop_distance"]))
    previous_timestamp: datetime | None = None
    previous_row: pd.Series | None = None

    def complete_open_trade(exit_price: Decimal, reason_code: str, exit_candle_id: int,
                            closed_at: datetime) -> None:
        nonlocal open_trade, equity, peak, max_drawdown
        if open_trade is None:
            return
        sign = Decimal("1") if open_trade.direction == "BUY" else Decimal("-1")
        gross = (exit_price-open_trade.entry)*sign*open_trade.size*value
        days = Decimal(str(max(0, (closed_at-open_trade.opened_at).total_seconds()/86400)))
        funding = open_trade.entry*open_trade.size*value*Decimal(str(settings.replay_funding_bps_per_day))/Decimal("10000")*days
        pnl = gross-open_trade.explicit_cost_zar-open_trade.slippage_cost_zar-funding
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak-equity)/peak*100)
        completed.append({"trade": open_trade, "exit_candle_id": exit_candle_id,
                          "exit_price": exit_price, "reason": reason_code, "pnl": pnl,
                          "gross": gross, "funding": funding, "closed_at": closed_at})
        events.append({"trade_id": open_trade.trade_id, "type": reason_code,
                       "candle_id": exit_candle_id, "time": closed_at,
                       "details": {"pnl_zar": str(pnl)}})
        open_trade = None

    for timestamp, row in featured.iterrows():
        timestamp_value = timestamp.to_pydatetime()
        if (request.segment_mode == "CONTINUOUS_ONLY" and previous_timestamp is not None
                and timestamp_value-previous_timestamp != timedelta(minutes=15) and open_trade
                and previous_row is not None):
            side = "bid_close" if open_trade.direction == "BUY" else "ask_close"
            boundary_price = (Decimal(str(previous_row[side])) if pd.notna(previous_row.get(side))
                              else Decimal(str(previous_row["close"])))
            complete_open_trade(boundary_price, "END_OF_SEGMENT",
                                int(previous_row["candle_id"]), previous_timestamp)
        previous_timestamp, previous_row = timestamp_value, row
        candle_id = int(row["candle_id"])
        opened = Decimal(str(row["open"])); high = Decimal(str(row["high"]))
        low = Decimal(str(row["low"])); close = Decimal(str(row["close"]))
        bid_close = Decimal(str(row["bid_close"])) if pd.notna(row.get("bid_close")) else None
        ask_close = Decimal(str(row["ask_close"])) if pd.notna(row.get("ask_close")) else None
        if open_trade:
            open_trade.holding += 1
            exit_side = "bid" if open_trade.direction == "BUY" else "ask"

            def exit_value(name: str, midpoint: Decimal) -> Decimal:
                value_at_side = row.get(f"{exit_side}_{name}")
                return Decimal(str(value_at_side)) if pd.notna(value_at_side) else midpoint

            resolved = resolve_candle_exit(
                open_trade.direction, stop=open_trade.stop, target=open_trade.target,
                opened=exit_value("open", opened), high=exit_value("high", high),
                low=exit_value("low", low), close=exit_value("close", close),
                holding_candles=open_trade.holding, max_holding_candles=32,
            )
            if resolved.closed:
                complete_open_trade(resolved.price, str(resolved.reason), candle_id, timestamp_value)
            continue
        if not bool(row.get("is_regular_session", True)):
            continue
        if model is not None and (
            request.mode == "VALIDATED_MODEL" or request.use_latest_model
        ):
            probability = float(row["_model_probability"])
            score=probability-0.5
            direction="BUY" if probability>=float(model_record["buy_threshold"]) else "SELL" if probability<=float(model_record["sell_threshold"]) else "HOLD"
        else:
            score=_technical_score(row)
            direction="BUY" if score>=0.15 else "SELL" if score<=-0.15 else "HOLD"
        if direction == "HOLD":
            continue
        atr=Decimal(str(row["atr"])); stop_distance=max(min_stop,atr*Decimal("2"))
        risk=equity*Decimal("0.0025")
        raw=risk/(stop_distance*value)
        size=(raw/increment).to_integral_value(rounding=ROUND_DOWN)*increment
        if size<minimum:
            events.append({"trade_id":None,"type":"RISK_REJECTED_MINIMUM_SIZE","candle_id":candle_id,
                           "time":timestamp.to_pydatetime(),"details":{"calculated_size":str(size)}})
            continue
        entry=entry_price(direction,midpoint=close,bid=bid_close,ask=ask_close)
        cost=transaction_cost_evidence(
            midpoint=close,bid=bid_close,ask=ask_close,size=size,value_per_price_point_zar=value,
            fallback_round_trip_cost_bps=Decimal(str(settings.model_round_trip_cost_bps)),
        )
        if (bid_close is None or ask_close is None) and cost_model:
            spread_column = {"OPTIMISTIC": "median_spread", "NORMAL": "p75_spread",
                             "STRESSED": "p95_spread"}[request.cost_mode]
            empirical = Decimal(str(cost_model[spread_column])) * size * value
            cost = type(cost)(empirical, empirical, False)
        slippage=entry*size*value*Decimal(str(settings.replay_slippage_bps))/Decimal("10000")
        stop=entry-stop_distance if direction=="BUY" else entry+stop_distance
        target=entry+stop_distance*Decimal("1.5") if direction=="BUY" else entry-stop_distance*Decimal("1.5")
        open_trade=OpenReplayTrade(str(uuid4()),direction,size,entry,stop,target,candle_id,
                                   timestamp.to_pydatetime(),cost.spread_cost_zar,
                                   cost.explicit_cost_zar,cost.spread_cost_in_price,slippage)
        events.append({"trade_id":open_trade.trade_id,"type":"OPENED","candle_id":candle_id,
                       "time":timestamp.to_pydatetime(),"details":{"score":score,"entry":str(entry)}})

    if open_trade:
        last = featured.iloc[-1]
        last_time = featured.index[-1].to_pydatetime()
        exit_side = "bid_close" if open_trade.direction == "BUY" else "ask_close"
        exit_price_value = (Decimal(str(last[exit_side])) if pd.notna(last.get(exit_side))
                            else Decimal(str(last["close"])))
        complete_open_trade(exit_price_value, "END_OF_REPLAY", int(last["candle_id"]), last_time)

    return _persist_run(settings,tenant_id,market,request,candles,model_record,config,digest,run_id,
                        equity,max_drawdown,completed,events)


def _persist_empty(settings: Settings, tenant_id: str, market: dict[str, object], request: ReplayRequest,
                   candles: list[dict[str, object]], reason: str) -> dict[str, object]:
    config={"mode":request.mode,"reason":reason}
    digest=hashlib.sha256(json.dumps({"market":str(market["market_id"]),"reason":reason,
                                     "count":len(candles)},sort_keys=True).encode()).hexdigest()
    return _persist_run(settings,tenant_id,market,request,candles,None,config,digest,str(uuid4()),
                        Decimal(request.initial_equity_zar),Decimal("0"),[],[],reason)


def _persist_run(settings: Settings,tenant_id: str,market: dict[str,object],request: ReplayRequest,
                 candles:list[dict[str,object]],model_record:dict[str,object]|None,config:dict[str,object],
                 digest:str,run_id:str,equity:Decimal,max_drawdown:Decimal,
                 trades:list[dict[str,object]],events:list[dict[str,object]],reason:str|None=None)->dict[str,object]:
    pnl=equity-Decimal(request.initial_equity_zar)
    promotable=request.mode=="VALIDATED_MODEL" and model_record is not None and reason is None
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute("SELECT replay_run_id,status,trade_count,realized_pnl_zar FROM app.replay_runs WHERE tenant_id=%s AND market_id=%s AND input_sha256=%s",(tenant_id,str(market["market_id"]),digest))
        existing=cursor.fetchone()
        if existing:
            return {"status":"CURRENT","replay_run_id":str(existing["replay_run_id"]),"trade_count":int(existing["trade_count"]),"realized_pnl_zar":str(existing["realized_pnl_zar"] or 0),"promotable":promotable}
        cursor.execute("""INSERT app.replay_runs(replay_run_id,tenant_id,market_id,strategy_version_id,model_version_id,mode,status,timeframe,start_time_utc,end_time_utc,initial_equity_zar,final_equity_zar,realized_pnl_zar,max_drawdown_pct,candle_count,trade_count,promotable,non_promotable_reason,input_sha256,configuration_json,completed_at_utc) VALUES(%s,%s,%s,%s,%s,%s,'COMPLETED','M15',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,SYSUTCDATETIME())""",
            (run_id,tenant_id,str(market["market_id"]),str(model_record["strategy_version_id"]) if model_record else None,str(model_record["model_version_id"]) if model_record else None,request.mode,candles[0]["open_time_utc"] if candles else None,candles[-1]["open_time_utc"] if candles else None,request.initial_equity_zar,equity,pnl,max_drawdown,len(candles),len(trades),promotable,None if promotable else reason or "DIAGNOSTIC_MODE",digest,json.dumps(config)))
        for item in trades:
            trade=item["trade"]
            cursor.execute(
                """INSERT app.replay_trades
                   (replay_trade_id,replay_run_id,direction,size,entry_candle_id,exit_candle_id,
                    entry_price,exit_price,stop_price,target_price,spread_cost_zar,
                    spread_cost_in_price,explicit_transaction_cost_zar,slippage_cost_zar,
                    funding_cost_zar,gross_pnl_zar,realized_pnl_zar,exit_reason,opened_at_utc,closed_at_utc)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (trade.trade_id,run_id,trade.direction,trade.size,trade.entry_candle_id,
                 item["exit_candle_id"],trade.entry,item["exit_price"],trade.stop,trade.target,
                 trade.spread_cost_zar,trade.spread_cost_in_price,trade.explicit_cost_zar,
                 trade.slippage_cost_zar,item["funding"],item.get("gross"),item["pnl"],item["reason"],
                 trade.opened_at,item["closed_at"]),
            )
        for event in events:
            cursor.execute("INSERT app.replay_events(replay_run_id,replay_trade_id,event_type,candle_id,details_json,occurred_at_utc) VALUES(%s,%s,%s,%s,%s,%s)",(run_id,event["trade_id"],event["type"],event["candle_id"],json.dumps(event["details"]),event["time"]))
        connection.commit()
    return {"status":"COMPLETED","replay_run_id":run_id,"symbol":market["symbol"],"mode":request.mode,
            "candle_count":len(candles),"trade_count":len(trades),"realized_pnl_zar":str(pnl),
            "final_equity_zar":str(equity),"max_drawdown_pct":str(max_drawdown),"promotable":promotable,
            "blocker":None if promotable else reason or "DIAGNOSTIC_MODE"}


def read_replay_runs(settings:Settings,tenant_id:str,limit:int=20)->dict[str,object]:
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute("""SELECT TOP (%s) r.replay_run_id,m.symbol,r.mode,r.status,r.candle_count,r.trade_count,r.initial_equity_zar,r.final_equity_zar,r.realized_pnl_zar,r.max_drawdown_pct,r.promotable,r.non_promotable_reason,r.started_at_utc,r.completed_at_utc FROM app.replay_runs r JOIN app.markets m ON m.market_id=r.market_id WHERE r.tenant_id=%s ORDER BY r.started_at_utc DESC""",(max(1,min(limit,100)),tenant_id))
        rows=cursor.fetchall()
    return {"runs":[{k:(v.replace(tzinfo=timezone.utc).isoformat() if hasattr(v,"tzinfo") else str(v) if v is not None else None) for k,v in row.items()} for row in rows]}
