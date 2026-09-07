from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.config import Settings
from app.database import open_database
from app.model_pipeline import (FEATURES, _market_frame, add_features, feature_vector_hash,
                                inference_feature_vector)
from app.order_lifecycle import record_created_intent, transition_intent
from app.position_sizing import PositionSizingInput, calculate_position_size
from app.shadow_trades import mark_shadow_trades, open_shadow_trade, record_shadow_candidate
from app.research_protocol import (
    PROTOCOL_VERSION,
    TARGET_CATALOG,
    apply_ensemble_disagreement,
    selective_directions_from_edges,
)


@dataclass(frozen=True)
class RiskInput:
    direction: str
    confidence: Decimal
    model_validated: bool
    market_data_fresh: bool
    reconciliation_clear: bool
    equity_zar: Decimal
    start_day_equity_zar: Decimal
    risk_per_trade_pct: Decimal
    daily_loss_limit_pct: Decimal
    open_positions: int
    market_positions: int
    max_open_positions: int
    max_positions_per_market: int
    current_price: Decimal
    atr: Decimal
    min_deal_size: Decimal | None
    size_increment: Decimal | None
    min_stop_distance: Decimal | None
    value_per_price_point_zar: Decimal | None
    consecutive_losses: int = 0
    profit_protection_state: str = "NORMAL"
    preferred_daily_return_pct: Decimal = Decimal("0")
    ledger_status: str = "CURRENT"
    reserved_risk_zar: Decimal = Decimal("0")
    max_portfolio_risk_pct: Decimal = Decimal("0.75")
    trades_today: int = 0
    max_trades_per_day: int = 6
    min_reward_risk_ratio: Decimal = Decimal("1.5")
    available_margin_zar: Decimal | None = None
    margin_factor_pct: Decimal | None = None


@dataclass(frozen=True)
class RiskResult:
    approved: bool
    reason: str
    planned_risk_zar: Decimal | None = None
    size: Decimal | None = None
    stop: Decimal | None = None
    take_profit: Decimal | None = None


def evaluate_risk(item: RiskInput) -> RiskResult:
    if item.direction not in {"BUY", "SELL"}:
        return RiskResult(False, "NO_TRADE_SIGNAL")
    if not item.model_validated:
        return RiskResult(False, "MODEL_NOT_VALIDATED")
    if not item.market_data_fresh:
        return RiskResult(False, "STALE_MARKET_DATA")
    if not item.reconciliation_clear:
        return RiskResult(False, "UNRESOLVED_RECONCILIATION")
    if item.ledger_status != "CURRENT":
        return RiskResult(False, f"DAILY_RISK_LEDGER_{item.ledger_status}")
    if item.equity_zar <= 0:
        return RiskResult(False, "INVALID_EQUITY")
    if item.start_day_equity_zar > 0:
        drawdown = (item.start_day_equity_zar - item.equity_zar) / item.start_day_equity_zar * 100
        if drawdown >= item.daily_loss_limit_pct:
            return RiskResult(False, "DAILY_LOSS_LIMIT")
    if item.profit_protection_state in {"DAILY_GAIN_LOCKED", "DAILY_TARGET_LOCKED"}:
        return RiskResult(False, "DAILY_PROFIT_LOCK")
    if item.consecutive_losses >= 4:
        return RiskResult(False, "CONSECUTIVE_LOSS_LIMIT")
    if item.open_positions >= item.max_open_positions:
        return RiskResult(False, "MAX_OPEN_POSITIONS")
    if item.market_positions >= item.max_positions_per_market:
        return RiskResult(False, "MAX_MARKET_POSITIONS")
    if item.trades_today >= item.max_trades_per_day:
        return RiskResult(False, "MAX_TRADES_PER_DAY")
    if item.min_reward_risk_ratio < Decimal("1"):
        return RiskResult(False, "INVALID_REWARD_RISK_POLICY")
    rules = (item.min_deal_size, item.size_increment, item.min_stop_distance,
             item.value_per_price_point_zar)
    if any(value is None or value <= 0 for value in rules):
        return RiskResult(False, "MISSING_BROKER_MARKET_RULES")

    assert item.min_deal_size and item.size_increment and item.min_stop_distance
    assert item.value_per_price_point_zar
    stop_distance = max(item.atr * Decimal("1.5"), item.min_stop_distance)
    if stop_distance <= 0 or item.current_price <= 0:
        return RiskResult(False, "INVALID_STOP_DISTANCE")
    # Profit objectives never appear in this calculation. Losses and profit
    # protection may only preserve or reduce risk, never increase it.
    risk_multiplier = Decimal("1")
    if item.consecutive_losses >= 3:
        risk_multiplier = Decimal("0.4")
    elif item.consecutive_losses >= 2:
        risk_multiplier = Decimal("0.8")
    if item.profit_protection_state == "PROFIT_PROTECTION":
        risk_multiplier = min(risk_multiplier, Decimal("0.5"))
    planned_risk = item.equity_zar * item.risk_per_trade_pct * risk_multiplier / Decimal("100")
    portfolio_limit = item.equity_zar * item.max_portfolio_risk_pct / Decimal("100")
    if item.reserved_risk_zar + planned_risk > portfolio_limit:
        return RiskResult(False, "MAX_PORTFOLIO_RISK")
    if item.available_margin_zar is None or item.margin_factor_pct is None or item.margin_factor_pct <= 0:
        return RiskResult(False, "MARGIN_EVIDENCE_MISSING")
    sign = Decimal("1") if item.direction == "BUY" else Decimal("-1")
    stop = item.current_price - sign * stop_distance
    sizing = calculate_position_size(PositionSizingInput(
        account_equity=item.equity_zar,
        risk_percentage=item.risk_per_trade_pct * risk_multiplier,
        entry_price=item.current_price,
        stop_price=stop,
        broker_minimum_size=item.min_deal_size,
        broker_size_increment=item.size_increment,
        value_per_point_account_currency=item.value_per_price_point_zar,
        margin_factor_pct=item.margin_factor_pct,
        available_margin=item.available_margin_zar,
    ))
    if not sizing.approved:
        return RiskResult(False, sizing.rejection_reason or "POSITION_SIZING_REJECTED")
    take_profit = item.current_price + sign * stop_distance * item.min_reward_risk_ratio
    return RiskResult(True, "SHADOW_RISK_APPROVED", sizing.estimated_stop_loss,
                      sizing.broker_rounded_size, stop, take_profit)


def _artifact(path: str, digest: str) -> dict[str, object]:
    artifact = Path(path)
    if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
        raise ValueError("MODEL_ARTIFACT_INTEGRITY_FAILED")
    bundle = joblib.load(artifact)
    if not isinstance(bundle, dict) or list(bundle.get("features") or []) != FEATURES:
        raise ValueError("MODEL_ARTIFACT_CONTRACT_FAILED")
    return bundle


def _signal(frame: pd.DataFrame, bundle: dict[str, object], buy: float, sell: float) -> tuple[str, Decimal, Decimal]:
    if str(bundle.get("research_protocol_version") or "") == PROTOCOL_VERSION:
        payload = dict(bundle.get("target_specification") or {})
        symbol = str(payload.get("symbol") or "")
        digest = str(payload.get("sha256") or "")
        specification = next((item for item in TARGET_CATALOG.get(symbol, ())
                              if item.digest == digest), None)
        if specification is None:
            raise ValueError("MODEL_TARGET_CONTRACT_FAILED")
        prepared = frame.copy()
        observed = prepared.get("observed_spread_bps", pd.Series(np.nan, index=prepared.index))
        fallback = float(bundle.get("fallback_spread") or 0)
        prepared["effective_cost_bps"] = np.maximum(
            observed.fillna(fallback).clip(lower=0).to_numpy(float), fallback,
        )
        featured = add_features(prepared, horizon=specification.horizon_bars, labelled=False)
        if featured.empty:
            raise ValueError("INSUFFICIENT_FEATURE_ROWS")
        row = featured.iloc[[-1]]
        model = bundle["model"]
        probabilities = model.predict_proba(row[FEATURES])
        edges = dict(bundle.get("edge_parameters") or {})
        directions, _ = selective_directions_from_edges(
            probabilities, model.classes_, row, specification,
            buy_move_bps=float(edges["buy_move_bps"]),
            sell_move_bps=float(edges["sell_move_bps"]),
        )
        directions = apply_ensemble_disagreement(model, row, directions)
        direction = "BUY" if directions[0] == 1 else "SELL" if directions[0] == -1 else "HOLD"
        class_value = 1 if direction == "BUY" else 2 if direction == "SELL" else 0
        lookup = {int(value): index for index, value in enumerate(model.classes_)}
        confidence = float(probabilities[0, lookup[class_value]]) if class_value in lookup else 0.0
        return direction, Decimal(str(confidence)), Decimal(str(row.iloc[0]["atr"]))
    row = inference_feature_vector(frame, horizon=int(bundle.get("horizon") or 4))
    probability = float(bundle["model"].predict_proba(row.to_frame().T)[0, 1])
    if not math.isfinite(probability):
        raise ValueError("NON_FINITE_MODEL_OUTPUT")
    direction = "BUY" if probability >= buy else "SELL" if probability <= sell else "HOLD"
    confidence = probability if direction != "SELL" else 1 - probability
    return direction, Decimal(str(confidence)), Decimal(str(row["atr"]))


def run_shadow_cycle(settings: Settings, tenant_id: str) -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT mode,new_orders_enabled FROM app.engine_controls WHERE tenant_id=%s", (tenant_id,))
        control = cursor.fetchone()
        if not control or control["mode"] != "SHADOW" or control["new_orders_enabled"]:
            return [{"result": "BLOCKED", "reason": "ENGINE_NOT_IN_SHADOW_MODE"}]
        cursor.execute(
            """SELECT TOP 1 ta.trading_account_id,ta.broker_connection_id
               FROM app.trading_accounts ta
               JOIN app.broker_connections bc ON bc.broker_connection_id=ta.broker_connection_id
               WHERE ta.tenant_id=%s AND bc.environment='demo' ORDER BY ta.created_at_utc""", (tenant_id,)
        )
        account = cursor.fetchone()
        if not account:
            return [{"result": "BLOCKED", "reason": "NO_DEMO_TRADING_ACCOUNT"}]
        outcomes.extend(mark_shadow_trades(cursor, tenant_id))

        cursor.execute(
            """SELECT m.market_id,m.symbol,sv.strategy_version_id,sv.buy_threshold,sv.sell_threshold,
                      mv.model_version_id,mv.artifact_path,mv.artifact_sha256,mv.status,
                      mv.registered_at_utc,mv.feature_version
               FROM app.markets m
               JOIN app.model_versions mv ON mv.market_id=m.market_id
               JOIN app.strategy_versions sv ON sv.strategy_version_id=mv.strategy_version_id
               JOIN app.strategies s ON s.strategy_id=sv.strategy_id
               WHERE m.enabled=1 AND m.signal_enabled=1 AND m.demo_trading_enabled=1
                 AND mv.status IN ('VALIDATED','REGISTERED')
                 AND s.tenant_id=%s AND s.status='ACTIVE' AND s.environment='DEMO'
                 AND mv.registered_at_utc=(SELECT MAX(x.registered_at_utc) FROM app.model_versions x
                                          WHERE x.market_id=m.market_id
                                            AND x.strategy_version_id=mv.strategy_version_id
                                            AND x.status IN ('VALIDATED','REGISTERED'))
               ORDER BY m.symbol""",
            (tenant_id,),
        )
        models = cursor.fetchall()
        for model in models:
            symbol, market_id = str(model["symbol"]), str(model["market_id"])
            frame = _market_frame(cursor, market_id)
            if len(frame) < 60:
                outcomes.append({"symbol": symbol, "result": "BLOCKED", "reason": "INSUFFICIENT_CANDLES"})
                continue
            cursor.execute(
                """SELECT TOP 1 candle_id,open_time_utc,[close],bid_close,ask_close FROM app.candles
                   WHERE market_id=%s AND timeframe='M15' AND completed=1
                     AND quality_status='PASS' AND is_regular_session=1
                   ORDER BY open_time_utc DESC""", (market_id,)
            )
            candle = cursor.fetchone()
            cursor.execute(
                """SELECT TOP (1) market_decision_id,decision,confidence,executable,blocker_code
                   FROM app.market_decisions WHERE tenant_id=%s AND market_id=%s AND candle_id=%s
                   ORDER BY generated_at_utc DESC""",
                (tenant_id, market_id, candle["candle_id"]),
            )
            combined_decision = cursor.fetchone()
            if not combined_decision:
                outcomes.append({"symbol": symbol, "result": "BLOCKED", "reason": "MACRO_DECISION_MISSING"})
                continue
            if not bool(combined_decision["executable"]):
                outcomes.append({"symbol": symbol, "result": "BLOCKED",
                                 "reason": combined_decision["blocker_code"] or "COMBINED_DECISION_BLOCKED",
                                 "direction": combined_decision["decision"]})
                continue
            try:
                bundle = _artifact(str(model["artifact_path"]), str(model["artifact_sha256"]))
                model_direction, _, atr = _signal(
                    frame, bundle,
                    float(model["buy_threshold"]), float(model["sell_threshold"]),
                )
            except ValueError as exc:
                outcomes.append({"symbol": symbol, "result": "BLOCKED", "reason": str(exc)})
                continue
            direction = str(combined_decision["decision"])
            confidence = Decimal(str(combined_decision["confidence"]))
            if model_direction != direction:
                outcomes.append({"symbol": symbol, "result": "BLOCKED", "reason": "MODEL_MACRO_DIRECTION_CONFLICT"})
                continue
            key = hashlib.sha256(f'{tenant_id}:{model["model_version_id"]}:{candle["candle_id"]}'.encode()).hexdigest()
            cursor.execute("SELECT signal_id FROM app.signals WHERE deterministic_key=%s", (key,))
            duplicate = cursor.fetchone()
            if duplicate:
                outcomes.append({"symbol": symbol, "result": "DUPLICATE_SKIPPED"})
                continue
            signal_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT app.signals(signal_id,tenant_id,trading_account_id,strategy_version_id,
                   model_version_id,market_id,candle_id,direction,confidence,atr,deterministic_key,market_decision_id)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (signal_id, tenant_id, str(account["trading_account_id"]), str(model["strategy_version_id"]),
                 str(model["model_version_id"]), market_id, candle["candle_id"], direction,
                 confidence, atr, key, str(combined_decision["market_decision_id"])),
            )
            result = _risk_from_database(cursor, tenant_id, account, model, candle, direction, confidence, atr)
            signal_time = candle["open_time_utc"].replace(tzinfo=timezone.utc)
            freeze_time = model["registered_at_utc"].replace(tzinfo=timezone.utc)
            feature_version = str(model.get("feature_version") or bundle.get("feature_version") or "UNKNOWN")
            vector_hash = feature_vector_hash(inference_feature_vector(
                frame, horizon=int(bundle.get("horizon") or 4)))
            shadow_entry = Decimal(str(candle["ask_close"] if direction == "BUY" and candle["ask_close"] is not None
                                       else candle["bid_close"] if direction == "SELL" and candle["bid_close"] is not None
                                       else candle["close"]))
            risk_pct = Decimal(str(result.get("risk_percentage") or 0))
            value_per_point = Decimal(str(result.get("value_per_price_point_zar") or 0))
            record_shadow_candidate(
                cursor, tenant_id=tenant_id, market_id=market_id, signal_id=signal_id,
                model_version_id=str(model["model_version_id"]), candle_id=int(candle["candle_id"]),
                direction=direction, approved=result["risk"].approved, reason=result["risk"].reason,
                feature_hash=vector_hash, feature_version=feature_version,
                freeze_timestamp=freeze_time, signal_timestamp=signal_time,
                equity=Decimal(str(result.get("equity") or 0)), risk_pct=risk_pct,
                entry=shadow_entry, stop=result["risk"].stop or shadow_entry,
                target=result["risk"].take_profit or shadow_entry,
                planned_risk=result["risk"].planned_risk_zar or Decimal("0"),
                size=result["risk"].size or Decimal("0"),
                value_per_point=value_per_point,
            )
            decision_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT app.risk_decisions(risk_decision_id,signal_id,risk_version_id,decision,reason_code,
                   equity_zar,planned_risk_zar,calculated_size,stop_level,take_profit_level)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (decision_id, signal_id, result["risk_version_id"],
                 "WOULD_APPROVE" if result["risk"].approved else "REJECTED", result["risk"].reason,
                 result["equity"], result["risk"].planned_risk_zar, result["risk"].size,
                 result["risk"].stop, result["risk"].take_profit),
            )
            if result["risk"].approved:
                intent_key = hashlib.sha256(f"shadow:{signal_id}".encode()).hexdigest()
                intent_id = str(uuid.uuid4())
                correlation_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT app.order_intents(order_intent_id,tenant_id,trading_account_id,signal_id,
                       risk_decision_id,market_id,direction,calculated_size,stop_level,take_profit_level,
                       risk_amount_zar,status,deterministic_key,client_reference)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CREATED',%s,%s)""",
                    (intent_id, tenant_id, str(account["trading_account_id"]), signal_id,
                     decision_id, market_id, direction, result["risk"].size, result["risk"].stop,
                     result["risk"].take_profit, result["risk"].planned_risk_zar, intent_key,
                     f"AUREX-SH-{intent_key[:20]}"),
                )
                record_created_intent(cursor, intent_id, correlation_id)
                transition_intent(
                    cursor, intent_id, from_status="CREATED", to_status="RISK_APPROVED",
                    event_type="RISK_APPROVED", correlation_id=correlation_id,
                    details={"mode": "SHADOW"},
                )
                transition_intent(
                    cursor, intent_id, from_status="RISK_APPROVED", to_status="WOULD_SUBMIT",
                    event_type="SHADOW_SUBMISSION_SIMULATED", correlation_id=correlation_id,
                    details={"broker_submission": False},
                )
                open_shadow_trade(
                    cursor, tenant_id=tenant_id, intent_id=intent_id, market_id=market_id,
                    direction=direction, size=result["risk"].size,
                    entry=shadow_entry, stop=result["risk"].stop,
                    target=result["risk"].take_profit, candle_id=int(candle["candle_id"]),
                    opened_at=candle["open_time_utc"].replace(tzinfo=timezone.utc),
                    value_per_price_point_zar=result["value_per_price_point_zar"],
                    cost_bps=Decimal(str(settings.model_round_trip_cost_bps)),
                    bid=Decimal(str(candle["bid_close"])) if candle["bid_close"] is not None else None,
                    ask=Decimal(str(candle["ask_close"])) if candle["ask_close"] is not None else None,
                    feature_vector_hash=vector_hash,
                    feature_version=feature_version,
                    model_version_id=str(model["model_version_id"]),
                    model_freeze_timestamp=freeze_time,
                )
            connection.commit()
            outcomes.append({"symbol": symbol, "result": "WOULD_SUBMIT" if result["risk"].approved else "REJECTED",
                             "reason": result["risk"].reason, "direction": direction,
                             "confidence": float(confidence)})
    return outcomes


def _risk_from_database(cursor: object, tenant_id: str, account: dict[str, object], model: dict[str, object],
                        candle: dict[str, object], direction: str, confidence: Decimal,
                        atr: Decimal) -> dict[str, object]:
    cursor.execute("SELECT * FROM app.risk_versions WHERE tenant_id=%s AND active=1", (tenant_id,))
    policy = cursor.fetchone()
    if not policy:
        raise ValueError("NO_ACTIVE_RISK_POLICY")
    account_id = str(account["trading_account_id"])
    cursor.execute(
        """SELECT TOP 1 opening_equity_zar,current_equity_zar,status,reserved_risk_zar,
                  consecutive_losses,profit_protection_state
           FROM app.daily_risk_ledger WHERE trading_account_id=%s
             AND ledger_date_sast=CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time' AS date)""",
        (account_id,),
    )
    ledger = cursor.fetchone()
    if not ledger:
        return {
            "risk": RiskResult(False, "DAILY_RISK_LEDGER_MISSING"),
            "risk_version_id": str(policy["risk_version_id"]), "equity": Decimal("0"),
        }
    equity = Decimal(str(ledger["current_equity_zar"]))
    start_equity = Decimal(str(ledger["opening_equity_zar"]))
    if ledger["status"] != "CURRENT":
        return {
            "risk": RiskResult(False, f"DAILY_RISK_LEDGER_{ledger['status']}"),
            "risk_version_id": str(policy["risk_version_id"]), "equity": equity,
        }
    cursor.execute("SELECT COUNT(*) total,SUM(CASE WHEN market_symbol=%s THEN 1 ELSE 0 END) market_total FROM app.positions WHERE trading_account_id=%s AND status='OPEN'", (model["symbol"], account_id))
    positions = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) unresolved FROM app.positions WHERE trading_account_id=%s AND status IN ('BROKER_MISSING','RECONCILING','RECONCILIATION_REQUIRED')", (account_id,))
    unresolved = int(cursor.fetchone()["unresolved"])
    cursor.execute("""SELECT TOP 1 min_deal_size,size_increment,min_stop_distance,
                             value_per_price_point_zar,market_status,margin_factor_pct
                      FROM app.broker_market_rules WHERE broker_connection_id=%s AND market_id=%s
                      AND observed_at_utc>=DATEADD(hour,-24,SYSUTCDATETIME()) ORDER BY observed_at_utc DESC""",
                   (str(account["broker_connection_id"]), str(model["market_id"])))
    rule = cursor.fetchone() or {}
    if rule.get("market_status") != "TRADEABLE":
        return {
            "risk": RiskResult(False, "MARKET_NOT_TRADEABLE"),
            "risk_version_id": str(policy["risk_version_id"]), "equity": equity,
        }
    cursor.execute(
        """SELECT COUNT(*) trade_count FROM app.order_intents
           WHERE trading_account_id=%s
             AND created_at_utc>=CAST(
                 (CAST(CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time' AS date)
                       AS datetime2) AT TIME ZONE 'South Africa Standard Time')
                  AT TIME ZONE 'UTC' AS datetime2)
             AND status NOT IN ('REJECTED','FAILED','CANCELLED')""", (account_id,),
    )
    trades_today = int(cursor.fetchone()["trade_count"] or 0)
    cursor.execute(
        """SELECT TOP (1) available_funds FROM app.account_snapshots
           WHERE trading_account_id=%s ORDER BY observed_at_utc DESC""", (account_id,),
    )
    snapshot = cursor.fetchone()
    available_margin = Decimal(str(snapshot["available_funds"])) if snapshot else None
    opened = candle["open_time_utc"]
    fresh = opened.replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc).replace(tzinfo=timezone.utc) - pd.Timedelta(minutes=45)
    risk = evaluate_risk(RiskInput(
        direction, confidence, model["status"] == "VALIDATED", fresh, unresolved == 0, equity,
        start_equity, Decimal(str(policy["risk_per_trade_pct"])), Decimal(str(policy["daily_loss_limit_pct"])),
        int(positions["total"] or 0), int(positions["market_total"] or 0), int(policy["max_open_positions"]),
        int(policy["max_positions_per_market"]), Decimal(str(candle["close"])), atr,
        Decimal(str(rule["min_deal_size"])) if rule.get("min_deal_size") else None,
        Decimal(str(rule["size_increment"])) if rule.get("size_increment") else None,
        Decimal(str(rule["min_stop_distance"])) if rule.get("min_stop_distance") else None,
        Decimal(str(rule["value_per_price_point_zar"])) if rule.get("value_per_price_point_zar") else None,
        int(ledger["consecutive_losses"] or 0), str(ledger["profit_protection_state"] or "NORMAL"),
        Decimal(str(policy["preferred_daily_return_pct"])),
        str(ledger["status"]), Decimal(str(ledger["reserved_risk_zar"] or 0)),
        Decimal(str(policy["max_portfolio_risk_pct"])), trades_today,
        int(policy["max_trades_per_day"]), Decimal(str(policy["min_reward_risk_ratio"])),
        available_margin,
        Decimal(str(rule["margin_factor_pct"])) if rule.get("margin_factor_pct") else None,
    ))
    return {"risk": risk, "risk_version_id": str(policy["risk_version_id"]), "equity": equity,
            "risk_percentage": Decimal(str(policy["risk_per_trade_pct"])),
            "value_per_price_point_zar": Decimal(str(rule["value_per_price_point_zar"]))}
