from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.config import Settings
from app.database import open_database
from app.forward_promotion import evaluate_forward_shadow
from app.market_intelligence import model_readiness, validate_market_data
from app.trading_operations import read_reconciliation_status, read_risk_status


def evidence_state(checks: dict[str, object]) -> str:
    if bool(checks.get("demo_auto_ready")):
        return "DEMO_TEST_READY"
    market_checks = checks.get("checks") or {}
    if not bool(market_checks.get("sufficient_data")):
        return "ACCUMULATING"
    if bool(market_checks.get("validated_model")):
        return "FORWARD_SHADOW"
    return "BLOCKED"


def run_market_quality_audits(settings: Settings) -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
    for market in markets:
        for timeframe in ("M5", "M15"):
            result = validate_market_data(settings, str(market["market_id"]), timeframe)
            outcomes.append({"symbol": str(market["symbol"]), "timeframe": timeframe, **result})
    return outcomes


def capture_forward_evidence(settings: Settings, tenant_id: str) -> list[dict[str, object]]:
    readiness = model_readiness(settings, tenant_id)
    risk = read_risk_status(settings, tenant_id)
    reconciliation = read_reconciliation_status(settings, tenant_id, limit=200)
    risk_status = str(risk.get("status") or "BLOCKED")
    reconciliation_clear = reconciliation.get("status") == "CLEAR"
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        for market in readiness["markets"]:
            symbol = str(market["symbol"])
            cursor.execute(
                """SELECT m.market_id,es.mode,
                          (SELECT TOP (1) candle_id FROM app.candles WHERE market_id=m.market_id
                           AND timeframe='M15' AND completed=1 AND quality_status='PASS'
                           AND is_regular_session=1
                           ORDER BY open_time_utc DESC) evidence_candle_id,
                          (SELECT COUNT(*) FROM app.candles WHERE market_id=m.market_id
                           AND timeframe='M15' AND completed=1 AND spread_close IS NOT NULL
                           AND is_regular_session=1) spread_rows,
                          (SELECT TOP (1) model_version_id FROM app.model_versions WHERE market_id=m.market_id
                           ORDER BY registered_at_utc DESC) model_version_id,
                          (SELECT TOP (1) market_decision_id FROM app.market_decisions
                           WHERE tenant_id=%s AND market_id=m.market_id ORDER BY generated_at_utc DESC) decision_id
                   FROM app.markets m LEFT JOIN app.market_execution_states es
                     ON es.market_id=m.market_id AND es.tenant_id=%s
                   WHERE m.symbol=%s AND m.enabled=1""",
                (tenant_id, tenant_id, symbol),
            )
            row = cursor.fetchone()
            if not row or not row["evidence_candle_id"]:
                outcomes.append({"symbol": symbol, "status": "SKIPPED", "reason": "NO_COMPLETED_M15"})
                continue
            cursor.execute(
                """SELECT TOP (1) market_decision_id,decision,executable,blocker_code
                   FROM app.market_decisions WHERE market_decision_id=%s""", (row["decision_id"],),
            )
            decision = cursor.fetchone() if row["decision_id"] else None
            cursor.execute(
                """SELECT COUNT(*) trade_count,
                          SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open_count,
                          SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) closed_count,
                          SUM(CASE WHEN status='CLOSED' AND realized_pnl_zar>0 THEN 1 ELSE 0 END) wins,
                          SUM(CASE WHEN status='CLOSED' AND realized_pnl_zar<0 THEN 1 ELSE 0 END) losses,
                          COALESCE(SUM(CASE WHEN status='CLOSED' THEN realized_pnl_zar ELSE 0 END),0) realized,
                          COALESCE(SUM(CASE WHEN status='OPEN' THEN unrealized_pnl_zar ELSE 0 END),0) unrealized
                   FROM app.shadow_trades WHERE tenant_id=%s AND market_id=%s""",
                (tenant_id, str(row["market_id"])),
            )
            shadow = cursor.fetchone()
            promotion = evaluate_forward_shadow(
                cursor, tenant_id, str(row["market_id"]),
                evidence_candle_id=int(row["evidence_candle_id"]), persist=True,
            )
            checks = dict(market.get("checks") or {})
            checks["forward_shadow_promoted"] = bool(promotion["passed"])
            checks["risk_current"] = risk_status == "CURRENT"
            checks["reconciliation_clear"] = reconciliation_clear
            blockers = [name for name, value in checks.items()
                        if name not in {"combined_decision", "combined_decision_blocker"} and value is False]
            state_input = {**market, "checks": checks}
            state = evidence_state(state_input)
            if state == "DEMO_TEST_READY" and (risk_status != "CURRENT" or not reconciliation_clear):
                state = "BLOCKED"
            cursor.execute(
                """IF NOT EXISTS(SELECT 1 FROM app.forward_evidence_snapshots
                                  WHERE tenant_id=%s AND market_id=%s AND evidence_candle_id=%s)
                   INSERT app.forward_evidence_snapshots
                     (forward_evidence_snapshot_id,tenant_id,market_id,evidence_candle_id,model_version_id,
                      market_decision_id,evidence_date_sast,first_m15_utc,latest_m15_utc,raw_m15_rows,
                      feature_complete_rows,required_feature_rows,spread_evidence_rows,quality_status,
                      model_status,market_decision,decision_executable,decision_blocker,execution_mode,
                      risk_status,reconciliation_clear,shadow_open_count,shadow_closed_count,shadow_win_count,
                      shadow_loss_count,shadow_realized_pnl_zar,shadow_unrealized_pnl_zar,evidence_state,blockers_json)
                   VALUES(%s,%s,%s,%s,%s,%s,
                     CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time' AS date),
                     %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (tenant_id,str(row["market_id"]),row["evidence_candle_id"],str(uuid4()),tenant_id,
                 str(row["market_id"]),row["evidence_candle_id"],str(row["model_version_id"]) if row["model_version_id"] else None,
                 str(decision["market_decision_id"]) if decision else None,market["earliest_candle_utc"],
                 market["latest_candle_utc"],market["raw_m15_rows"],market["feature_complete_rows"],
                 market["required_rows"],int(row["spread_rows"] or 0),market["quality_status"],
                 market["model_status"],str(decision["decision"]) if decision else "NONE",
                 bool(decision["executable"]) if decision else False,
                 str(decision["blocker_code"]) if decision and decision["blocker_code"] else None,
                 str(row["mode"] or "SHADOW"),risk_status,reconciliation_clear,
                 int(shadow["open_count"] or 0),int(shadow["closed_count"] or 0),
                 int(shadow["wins"] or 0),int(shadow["losses"] or 0),
                 Decimal(str(shadow["realized"] or 0)),Decimal(str(shadow["unrealized"] or 0)),
                 state,json.dumps(blockers)),
            )
            outcomes.append({"symbol": symbol, "status": "CAPTURED" if cursor.rowcount else "CURRENT",
                             "state": state, "feature_rows": market["feature_complete_rows"],
                             "required_rows": market["required_rows"], "blockers": blockers,
                             "forward_shadow": promotion})
        connection.commit()
    return outcomes


def read_forward_evidence(settings: Settings, tenant_id: str, limit: int = 200) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) f.forward_evidence_snapshot_id,m.symbol,f.evidence_date_sast,
                      f.first_m15_utc,f.latest_m15_utc,f.raw_m15_rows,f.feature_complete_rows,
                      f.required_feature_rows,f.spread_evidence_rows,f.quality_status,f.model_status,
                      f.market_decision,f.decision_executable,f.decision_blocker,f.execution_mode,
                      f.risk_status,f.reconciliation_clear,f.shadow_open_count,f.shadow_closed_count,
                      f.shadow_win_count,f.shadow_loss_count,f.shadow_realized_pnl_zar,
                      f.shadow_unrealized_pnl_zar,f.evidence_state,f.blockers_json,f.captured_at_utc
               FROM app.forward_evidence_snapshots f JOIN app.markets m ON m.market_id=f.market_id
               WHERE f.tenant_id=%s ORDER BY f.captured_at_utc DESC,m.symbol""",
            (max(1,min(limit,1000)),tenant_id),
        )
        rows = cursor.fetchall()
    snapshots=[]
    for row in rows:
        item={name:_json_value(value) for name,value in row.items() if name!="blockers_json"}
        item["blockers"]=json.loads(row["blockers_json"])
        snapshots.append(item)
    latest={}
    for item in snapshots:
        latest.setdefault(str(item["symbol"]),item)
    return {"latest":list(latest.values()),"snapshots":snapshots,
            "policy":"FORWARD_EVIDENCE_NEVER_OVERRIDES_VALIDATION_OR_RISK_GATES"}


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    return value
