from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.research_protocol_store import insert_lifecycle_event


SAST = ZoneInfo("Africa/Johannesburg")


def read_forward_shadow_promotions(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
        evaluations = [
            {"symbol": str(market["symbol"]),
             **_json_payload(evaluate_forward_shadow(cursor, tenant_id, str(market["market_id"])))}
            for market in markets
        ]
    return {
        "status": "PROMOTED" if any(item["passed"] for item in evaluations) else "ACCUMULATING",
        "markets": evaluations,
        "policy_authority": "FORWARD_SHADOW_EVIDENCE_CANNOT_OVERRIDE_RISK_OR_BROKER_GATES",
    }


def evaluate_forward_shadow(
    cursor: object,
    tenant_id: str,
    market_id: str,
    *,
    evidence_candle_id: int | None = None,
    persist: bool = False,
) -> dict[str, object]:
    """Evaluate only closed shadow trades produced by the latest validated model."""
    cursor.execute(
        """SELECT TOP (1) * FROM app.forward_shadow_policies
           WHERE tenant_id=%s AND active=1 ORDER BY policy_version DESC""",
        (tenant_id,),
    )
    policy = cursor.fetchone()
    if not policy:
        return _unavailable("NO_ACTIVE_FORWARD_SHADOW_POLICY")

    cursor.execute(
        """SELECT TOP (1) model_version_id,version,status
           FROM app.model_versions WHERE market_id=%s AND status='VALIDATED'
           ORDER BY registered_at_utc DESC""",
        (market_id,),
    )
    model = cursor.fetchone()
    if not model:
        return _unavailable("NO_VALIDATED_MODEL", policy=policy)

    cursor.execute(
        """SELECT st.closed_at_utc,st.realized_pnl_zar,st.estimated_entry_cost_zar
           FROM app.shadow_trades st
           JOIN app.order_intents oi ON oi.order_intent_id=st.order_intent_id
           JOIN app.signals s ON s.signal_id=oi.signal_id
           WHERE st.tenant_id=%s AND st.market_id=%s AND st.status='CLOSED'
             AND s.model_version_id=%s
           ORDER BY st.closed_at_utc,st.shadow_trade_id""",
        (tenant_id, market_id, str(model["model_version_id"])),
    )
    trades = cursor.fetchall()
    pnl = [Decimal(str(item["realized_pnl_zar"] or 0)) for item in trades]
    wins = sum(1 for value in pnl if value > 0)
    losses = sum(1 for value in pnl if value < 0)
    gross_profit = sum((value for value in pnl if value > 0), Decimal("0"))
    gross_loss = -sum((value for value in pnl if value < 0), Decimal("0"))
    profit_factor = gross_profit / gross_loss if gross_loss else (Decimal("999") if gross_profit else Decimal("0"))
    closed = len(trades)
    days = len({item["closed_at_utc"].replace(tzinfo=timezone.utc).astimezone(SAST).date()
                for item in trades if item["closed_at_utc"]})
    realized = sum(pnl, Decimal("0"))
    expectancy = realized / closed if closed else Decimal("0")
    cost_count = sum(1 for item in trades if item["estimated_entry_cost_zar"] is not None
                     and Decimal(str(item["estimated_entry_cost_zar"])) >= 0)
    cost_coverage = Decimal(cost_count) / Decimal(closed) if closed else Decimal("0")
    consecutive = maximum_consecutive_losses(pnl)

    cursor.execute(
        """SELECT TOP (1) s.equity FROM app.account_snapshots s
           JOIN app.trading_accounts ta ON ta.trading_account_id=s.trading_account_id
           WHERE ta.tenant_id=%s AND s.equity>0 ORDER BY s.observed_at_utc DESC""",
        (tenant_id,),
    )
    equity_row = cursor.fetchone()
    reference_equity = Decimal(str(equity_row["equity"])) if equity_row else Decimal("0")
    drawdown_pct = maximum_drawdown_pct(pnl, reference_equity)

    checks = {
        "minimum_closed_trades": closed >= int(policy["minimum_closed_trades"]),
        "minimum_trading_days": days >= int(policy["minimum_trading_days"]),
        "positive_expectancy": expectancy > Decimal(str(policy["minimum_expectancy_zar"])),
        "minimum_profit_factor": profit_factor >= Decimal(str(policy["minimum_profit_factor"])),
        "maximum_drawdown": drawdown_pct <= Decimal(str(policy["maximum_drawdown_pct"])),
        "maximum_consecutive_losses": consecutive <= int(policy["maximum_consecutive_losses"]),
        "cost_evidence_complete": not bool(policy["require_cost_evidence"]) or cost_coverage == Decimal("1"),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    result: dict[str, object] = {
        "status": "PASSED" if not blockers else "ACCUMULATING",
        "passed": not blockers,
        "model_version_id": str(model["model_version_id"]),
        "model_version": str(model["version"]),
        "closed_trades": closed,
        "trading_days": days,
        "wins": wins,
        "losses": losses,
        "win_rate": Decimal(wins) / Decimal(closed) if closed else Decimal("0"),
        "profit_factor": profit_factor,
        "expectancy_zar": expectancy,
        "maximum_drawdown_pct": drawdown_pct,
        "maximum_consecutive_losses": consecutive,
        "cost_evidence_coverage": cost_coverage,
        "realized_pnl_zar": realized,
        "reference_equity_zar": reference_equity,
        "checks": checks,
        "blockers": blockers,
        "policy": _policy_payload(policy),
    }
    if persist and evidence_candle_id is not None:
        _persist(cursor, tenant_id, market_id, int(evidence_candle_id), policy, result)
    return result


def maximum_consecutive_losses(pnl: list[Decimal]) -> int:
    maximum = current = 0
    for value in pnl:
        current = current + 1 if value < 0 else 0
        maximum = max(maximum, current)
    return maximum


def maximum_drawdown_pct(pnl: list[Decimal], reference_equity: Decimal) -> Decimal:
    if reference_equity <= 0:
        return Decimal("999") if pnl else Decimal("0")
    cumulative = peak = maximum = Decimal("0")
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum / reference_equity * Decimal("100")


def _unavailable(reason: str, *, policy: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": "BLOCKED", "passed": False, "model_version_id": None,
        "closed_trades": 0, "trading_days": 0, "wins": 0, "losses": 0,
        "win_rate": Decimal("0"), "profit_factor": Decimal("0"),
        "expectancy_zar": Decimal("0"), "maximum_drawdown_pct": Decimal("0"),
        "maximum_consecutive_losses": 0, "cost_evidence_coverage": Decimal("0"),
        "realized_pnl_zar": Decimal("0"), "checks": {}, "blockers": [reason],
        "policy": _policy_payload(policy) if policy else None,
    }


def _policy_payload(policy: dict[str, object]) -> dict[str, object]:
    return {
        "version": int(policy["policy_version"]),
        "minimum_closed_trades": int(policy["minimum_closed_trades"]),
        "minimum_trading_days": int(policy["minimum_trading_days"]),
        "minimum_profit_factor": str(policy["minimum_profit_factor"]),
        "minimum_expectancy_zar": str(policy["minimum_expectancy_zar"]),
        "maximum_drawdown_pct": str(policy["maximum_drawdown_pct"]),
        "maximum_consecutive_losses": int(policy["maximum_consecutive_losses"]),
        "require_cost_evidence": bool(policy["require_cost_evidence"]),
    }


def _persist(
    cursor: object, tenant_id: str, market_id: str, evidence_candle_id: int,
    policy: dict[str, object], result: dict[str, object],
) -> None:
    cursor.execute(
        """IF NOT EXISTS(
             SELECT 1 FROM app.forward_shadow_evaluations
             WHERE tenant_id=%s AND market_id=%s AND model_version_id=%s AND evidence_candle_id=%s)
           INSERT app.forward_shadow_evaluations
             (forward_shadow_evaluation_id,tenant_id,market_id,model_version_id,
              forward_shadow_policy_id,evidence_candle_id,closed_trades,trading_days,wins,losses,
              win_rate,profit_factor,expectancy_zar,maximum_drawdown_pct,
              maximum_consecutive_losses,cost_evidence_coverage,realized_pnl_zar,passed,blockers_json)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (tenant_id, market_id, result["model_version_id"], evidence_candle_id,
         str(uuid4()), tenant_id, market_id, result["model_version_id"],
         str(policy["forward_shadow_policy_id"]), evidence_candle_id,
         result["closed_trades"], result["trading_days"], result["wins"], result["losses"],
         result["win_rate"], result["profit_factor"], result["expectancy_zar"],
         result["maximum_drawdown_pct"], result["maximum_consecutive_losses"],
         result["cost_evidence_coverage"], result["realized_pnl_zar"],
        bool(result["passed"]), json.dumps(result["blockers"])),
    )
    if bool(result["passed"]):
        cursor.execute(
            """SELECT mv.holdout_candidate_id,mv.research_lineage_id
               FROM app.model_versions mv WHERE mv.model_version_id=%s""",
            (result["model_version_id"],),
        )
        governed = cursor.fetchone() or {}
        cursor.execute(
            """SELECT COUNT(*) event_count FROM app.candidate_lifecycle_events
               WHERE tenant_id=%s AND market_id=%s AND model_version_id=%s AND to_state='PROMOTED'""",
            (tenant_id, market_id, result["model_version_id"]),
        )
        if int((cursor.fetchone() or {}).get("event_count") or 0) == 0:
            insert_lifecycle_event(
                cursor, tenant_id=tenant_id, market_id=market_id,
                research_lineage_id=str(governed["research_lineage_id"])
                if governed.get("research_lineage_id") else None,
                holdout_candidate_id=str(governed["holdout_candidate_id"])
                if governed.get("holdout_candidate_id") else None,
                model_version_id=str(result["model_version_id"]),
                from_state="FORWARD_SHADOW", to_state="PROMOTED",
                reason="Sustained forward-shadow policy passed",
                evidence={"policy": result["policy"], "checks": result["checks"],
                          "closed_trades": result["closed_trades"],
                          "trading_days": result["trading_days"],
                          "execution_enabled": False},
            )


def _json_payload(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_payload(item) for item in value]
    return value
