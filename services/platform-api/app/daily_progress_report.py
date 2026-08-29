from __future__ import annotations

import hashlib
import html
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.config import Settings
from app.database import open_database
from app.email_delivery import send_email
from app.holdout_service import read_holdout_status
from app.market_intelligence import model_readiness
from app.trading_operations import read_model_validation


logger = logging.getLogger("aurex.daily_progress_report")
SAST = ZoneInfo("Africa/Johannesburg")


@dataclass(frozen=True)
class ProgressReport:
    subject: str
    plain_text: str
    html: str
    summary: dict[str, object]


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def _display(value: object, fallback: str = "—") -> str:
    return fallback if value is None else str(value)


def _collect_database_summary(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.symbol,
                      SUM(CASE WHEN c.timeframe='M5' AND c.completed=1 THEN 1 ELSE 0 END) m5_rows,
                      SUM(CASE WHEN c.timeframe='M15' AND c.completed=1 THEN 1 ELSE 0 END) m15_rows,
                      SUM(CASE WHEN c.timeframe='M5' AND c.source LIKE 'IG%%' AND c.completed=1 THEN 1 ELSE 0 END) ig_m5_rows,
                      SUM(CASE WHEN c.timeframe='M5' AND c.source LIKE 'DUKASCOPY%%' AND c.completed=1 THEN 1 ELSE 0 END) dukascopy_m5_rows,
                      MAX(CASE WHEN c.timeframe='M5' AND c.completed=1 THEN c.open_time_utc END) latest_m5_utc,
                      MAX(CASE WHEN c.timeframe='M15' AND c.completed=1 THEN c.open_time_utc END) latest_m15_utc
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
               WHERE m.enabled=1 GROUP BY m.symbol ORDER BY m.symbol"""
        )
        collection = cursor.fetchall()
        cursor.execute(
            """SELECT COUNT(1) total,
                      COALESCE(SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END),0) open_count,
                      COALESCE(SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END),0) closed_count,
                      COALESCE(SUM(CASE WHEN status='CLOSED' AND realized_pnl_zar>0 THEN 1 ELSE 0 END),0) wins,
                      COALESCE(SUM(CASE WHEN status='CLOSED' AND realized_pnl_zar<0 THEN 1 ELSE 0 END),0) losses,
                      COALESCE(SUM(CASE WHEN status='CLOSED' THEN realized_pnl_zar ELSE 0 END),0) realized_pnl_zar
               FROM app.shadow_trades WHERE tenant_id=%s""", (tenant_id,),
        )
        shadow = cursor.fetchone()
        cursor.execute(
            """SELECT status,COUNT(1) intent_count FROM app.order_intents
               WHERE tenant_id=%s GROUP BY status ORDER BY status""", (tenant_id,),
        )
        intents = cursor.fetchall()
        cursor.execute(
            """SELECT mode,new_orders_enabled,pause_reason FROM app.engine_controls
               WHERE tenant_id=%s""", (tenant_id,),
        )
        engine = cursor.fetchone()
        cursor.execute(
            """SELECT COUNT(1) attempt_count,
                      COALESCE(SUM(CASE WHEN submission_count>0 THEN 1 ELSE 0 END),0) submitted_count
               FROM app.demo_execution_attempts WHERE tenant_id=%s""", (tenant_id,),
        )
        demo = cursor.fetchone()
        cursor.execute(
            """WITH ranked AS (
                   SELECT f.*,m.symbol,ROW_NUMBER() OVER(
                       PARTITION BY f.market_id ORDER BY f.captured_at_utc DESC
                   ) evidence_rank
                   FROM app.forward_evidence_snapshots f JOIN app.markets m ON m.market_id=f.market_id
                   WHERE f.tenant_id=%s
               )
               SELECT symbol,evidence_state,decision_blocker,shadow_closed_count,
                      shadow_realized_pnl_zar,captured_at_utc
               FROM ranked WHERE evidence_rank=1 ORDER BY symbol""", (tenant_id,),
        )
        forward = cursor.fetchall()
    return {
        "collection": collection, "shadow": shadow, "intents": intents,
        "engine": engine, "demo": demo, "forward": forward,
    }


def build_daily_progress_report(
    settings: Settings, tenant_id: str, report_date_sast: date,
) -> ProgressReport:
    readiness = model_readiness(settings, tenant_id)
    validations = read_model_validation(settings, tenant_id)
    holdout = read_holdout_status(settings, tenant_id)
    database = _collect_database_summary(settings, tenant_id)
    validation_by_market = {item["market"]: item for item in validations["models"]}
    collection_by_market = {str(item["symbol"]): item for item in database["collection"]}

    markets: list[dict[str, object]] = []
    blockers: list[str] = []
    improvements: list[str] = []
    for market in readiness["markets"]:
        symbol = str(market["symbol"])
        validation = validation_by_market.get(symbol) or {}
        collection = collection_by_market.get(symbol) or {}
        market_blockers = list(market.get("blockers") or [])
        if market.get("model_status") != "VALIDATED":
            market_blockers.append("MODEL_NOT_VALIDATED")
        if market.get("quality_status") != "PASS":
            market_blockers.append("EXECUTION_QUALITY_NOT_CURRENT")
        if validation.get("auc") is not None and float(validation["auc"]) < settings.model_acceptance_auc:
            market_blockers.append("AUC_BELOW_ACCEPTANCE")
        if validation.get("expectancy") is not None and float(validation["expectancy"]) <= 0:
            market_blockers.append("NON_POSITIVE_COST_AWARE_EXPECTANCY")
        if validation.get("profit_factor") is not None and float(validation["profit_factor"]) < settings.holdout_minimum_profit_factor:
            market_blockers.append("PROFIT_FACTOR_BELOW_1_10")
        if validation.get("baseline_outperformed") is False:
            market_blockers.append("BASELINE_NOT_OUTPERFORMED")
        market_blockers = list(dict.fromkeys(str(item) for item in market_blockers))
        blockers.extend(f"{symbol}: {item}" for item in market_blockers)
        markets.append({
            "symbol": symbol,
            "feature_rows": int(market.get("feature_complete_rows") or 0),
            "required_rows": int(market.get("required_rows") or settings.model_minimum_rows),
            "model_status": market.get("model_status") or "NONE",
            "model_version": market.get("model_version"),
            "quality_status": market.get("quality_status") or "UNKNOWN",
            "execution_mode": market.get("execution_mode") or "SHADOW",
            "auc": validation.get("auc"),
            "profit_factor": validation.get("profit_factor"),
            "expectancy": validation.get("expectancy"),
            "baseline_outperformed": validation.get("baseline_outperformed"),
            "m5_rows": int(collection.get("m5_rows") or 0),
            "m15_rows": int(collection.get("m15_rows") or 0),
            "ig_m5_rows": int(collection.get("ig_m5_rows") or 0),
            "dukascopy_m5_rows": int(collection.get("dukascopy_m5_rows") or 0),
            "latest_m5_utc": collection.get("latest_m5_utc"),
            "latest_m15_utc": collection.get("latest_m15_utc"),
            "blockers": market_blockers,
        })

    latest_holdout_block = (holdout.get("blocked_attempts") or [None])[0]
    if latest_holdout_block and latest_holdout_block.get("outcome"):
        outcome = latest_holdout_block["outcome"]
        shortage = max(0, int(outcome["required_holdout_rows"]) - int(outcome["available_holdout_rows"]))
        blockers.append(
            f"{latest_holdout_block['symbol']}: holdout {outcome['available_holdout_rows']}/"
            f"{outcome['required_holdout_rows']} ({shortage} independent rows still required)"
        )
        improvements.append(
            f"Continue uninterrupted IG collection for {latest_holdout_block['symbol']} until at least "
            f"{shortage} additional feature-complete holdout rows exist; do not lower the holdout floor."
        )
    if any(item["model_status"] != "VALIDATED" for item in markets):
        improvements.append(
            "Keep model research market-specific; require positive cost-aware expectancy, baseline "
            "outperformance, calibration, drift and regime evidence before validation."
        )
    if any(item["quality_status"] != "PASS" for item in markets):
        improvements.append(
            "Investigate recent IG freshness or gaps while retaining provider boundaries; do not fill "
            "missing data with fabricated candles or unbounded historical requests."
        )
    improvements.append(
        "Keep the engine in SHADOW with new orders disabled until one frozen candidate passes its "
        "single-use holdout and then accumulates sustained forward-shadow evidence."
    )
    blockers = list(dict.fromkeys(blockers))
    improvements = list(dict.fromkeys(improvements))

    summary = {
        "report_date_sast": report_date_sast,
        "generated_at_utc": datetime.now(timezone.utc),
        "markets": markets,
        "trading": {
            "engine": database["engine"], "shadow": database["shadow"],
            "order_intents": database["intents"], "demo_execution": database["demo"],
            "forward_evidence": database["forward"],
        },
        "holdout": holdout,
        "blockers": blockers,
        "improvements": improvements,
        "safety": {"broker_environment": settings.broker_environment,
                   "trading_mode": settings.trading_mode, "execution_enabled": False},
    }

    market_lines = []
    for item in markets:
        market_lines.append(
            f"- {item['symbol']}: features {item['feature_rows']:,}/{item['required_rows']:,}; "
            f"model {item['model_status']}; quality {item['quality_status']}; "
            f"M5 {item['m5_rows']:,}; M15 {item['m15_rows']:,}; "
            f"latest M5 UTC {_display(item['latest_m5_utc'])}; "
            f"AUC {_display(item['auc'])}; PF {_display(item['profit_factor'])}; "
            f"expectancy {_display(item['expectancy'])}."
        )
    shadow = database["shadow"] or {}
    engine = database["engine"] or {}
    demo = database["demo"] or {}
    plain = "\n".join([
        f"Aurex daily progress report — {report_date_sast.isoformat()} (South Africa)", "",
        "TRAINING AND DATA COLLECTION", *market_lines, "",
        "TRADING / SHADOW EVIDENCE",
        f"- Engine mode: {_display(engine.get('mode'))}; new orders enabled: {bool(engine.get('new_orders_enabled'))}.",
        f"- Shadow trades: {int(shadow.get('total') or 0)} total, {int(shadow.get('open_count') or 0)} open, "
        f"{int(shadow.get('closed_count') or 0)} closed; realized P/L ZAR {_display(shadow.get('realized_pnl_zar'), '0')}.",
        f"- IG Demo attempts: {int(demo.get('attempt_count') or 0)}; submissions: {int(demo.get('submitted_count') or 0)}.", "",
        "OUTSTANDING BLOCKERS", *(f"- {item}" for item in blockers), "",
        "SAFE IMPROVEMENTS", *(f"- {item}" for item in improvements), "",
        "SAFETY STATUS",
        "No broker order was enabled or submitted by this report. Research and reporting have no execution authority.",
    ])

    rows = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(_display(value))}</td>" for value in (
                item["symbol"], f"{item['feature_rows']:,}/{item['required_rows']:,}",
                item["model_status"], item["quality_status"], f"{item['m5_rows']:,}",
                f"{item['m15_rows']:,}", _display(item["auc"]), _display(item["profit_factor"]),
                _display(item["expectancy"]),
            )
        ) + "</tr>" for item in markets
    )
    trading_sentence = (
        f"Shadow: {int(shadow.get('total') or 0)} total / "
        f"{int(shadow.get('closed_count') or 0)} closed. "
        f"IG Demo submissions: {int(demo.get('submitted_count') or 0)}."
    )
    html_body = f"""<!doctype html><html><body style="font-family:Arial,sans-serif;color:#172b4d;background:#f5f7fa;padding:24px">
      <div style="max-width:920px;margin:auto;background:white;border:1px solid #e4e7ec;border-radius:12px;padding:24px">
      <p style="color:#2563eb;font-weight:700;letter-spacing:.08em">AUREX DAILY EVIDENCE</p>
      <h1 style="margin-top:0">Progress report — {report_date_sast.isoformat()}</h1>
      <p>Training, trading and collection evidence as of {datetime.now(SAST).strftime('%d %b %Y %H:%M SAST')}.</p>
      <h2>Training and data collection</h2><div style="overflow:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr>{''.join(f'<th style="text-align:left;border-bottom:1px solid #ddd;padding:8px">{name}</th>' for name in ('Market','Features','Model','Quality','M5','M15','AUC','PF','Expectancy'))}</tr></thead>
      <tbody>{rows}</tbody></table></div>
      <h2>Trading / shadow evidence</h2>
      <p>Engine <strong>{html.escape(_display(engine.get('mode')))}</strong>; new orders <strong>{'enabled' if engine.get('new_orders_enabled') else 'disabled'}</strong>. {html.escape(trading_sentence)}</p>
      <h2>Outstanding blockers</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in blockers)}</ul>
      <h2>Safe improvements</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in improvements)}</ul>
      <p style="padding:12px;background:#fffaeb;color:#93370d;border-radius:8px"><strong>Safety:</strong> This report has no execution authority. No order was enabled or submitted.</p>
      </div></body></html>"""
    return ProgressReport(
        subject=f"Aurex daily progress — {report_date_sast.isoformat()}",
        plain_text=plain, html=html_body, summary=summary,
    )


def send_due_daily_progress_reports(
    settings: Settings, *, force: bool = False, retry_failed: bool = False,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    if not settings.daily_progress_report_enabled:
        return [{"status": "DISABLED"}]
    moment = now or datetime.now(timezone.utc)
    local = moment.astimezone(SAST)
    if not force and local.hour < settings.daily_progress_report_hour_sast:
        return [{"status": "NOT_DUE", "report_date_sast": local.date().isoformat()}]
    recipient = settings.trade_report_recipient or settings.owner_email or settings.smtp_from_email
    if not settings.smtp_configured or not recipient:
        return [{"status": "NOT_CONFIGURED"}]
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenants = [str(row[0]) for row in cursor.fetchall()]
    outcomes: list[dict[str, object]] = []
    for tenant_id in tenants:
        try:
            retry_report_id: str | None = None
            with open_database(settings) as connection:
                cursor = connection.cursor(as_dict=True)
                cursor.execute(
                    """SELECT daily_progress_report_id,status,sent_at_utc,failure_code
                       FROM app.daily_progress_reports
                       WHERE tenant_id=%s AND report_date_sast=%s""", (tenant_id, local.date()),
                )
                existing = cursor.fetchone()
            if existing:
                if force and retry_failed and existing["status"] == "FAILED":
                    retry_report_id = str(existing["daily_progress_report_id"])
                else:
                    outcomes.append({"tenant_id": tenant_id, "status": "CURRENT",
                                     "delivery_status": existing["status"],
                                     "sent_at_utc": existing["sent_at_utc"],
                                     "failure_code": existing["failure_code"]})
                    continue
            report = build_daily_progress_report(settings, tenant_id, local.date())
            summary_json = json.dumps(report.summary, default=_json_default)
            body_digest = hashlib.sha256(report.plain_text.encode()).hexdigest()
            report_id = retry_report_id or str(uuid4())
            with open_database(settings) as connection:
                cursor = connection.cursor(as_dict=True)
                if retry_report_id:
                    cursor.execute(
                        """UPDATE app.daily_progress_reports SET recipient_email=%s,subject=%s,
                                  body_sha256=%s,status='SENDING',summary_json=%s,
                                  claimed_at_utc=SYSUTCDATETIME(),sent_at_utc=NULL,failed_at_utc=NULL,
                                  failure_code=NULL
                           WHERE daily_progress_report_id=%s AND status='FAILED'""",
                        (recipient, report.subject, body_digest, summary_json, report_id),
                    )
                    if cursor.rowcount != 1:
                        connection.rollback()
                        outcomes.append({"tenant_id": tenant_id, "status": "CURRENT"})
                        continue
                else:
                    cursor.execute(
                        """INSERT app.daily_progress_reports
                             (daily_progress_report_id,tenant_id,report_date_sast,recipient_email,
                              subject,body_sha256,status,summary_json)
                           VALUES(%s,%s,%s,%s,%s,%s,'SENDING',%s)""",
                        (report_id, tenant_id, local.date(), recipient, report.subject, body_digest, summary_json),
                    )
                connection.commit()
            try:
                send_email(settings, recipient=recipient, subject=report.subject,
                           plain_text=report.plain_text, html=report.html)
            except Exception as exc:
                with open_database(settings) as connection:
                    cursor = connection.cursor()
                    cursor.execute(
                        """UPDATE app.daily_progress_reports SET status='FAILED',
                                  failed_at_utc=SYSUTCDATETIME(),failure_code=%s
                           WHERE daily_progress_report_id=%s AND status='SENDING'""",
                        (type(exc).__name__, report_id),
                    )
                    connection.commit()
                logger.warning("Daily progress report delivery failed", extra={
                    "worker": "health_monitor", "operation": "daily_progress.email",
                    "result": type(exc).__name__,
                })
                outcomes.append({"tenant_id": tenant_id, "status": "FAILED",
                                 "failure_code": type(exc).__name__})
                continue
            with open_database(settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE app.daily_progress_reports SET status='SENT',sent_at_utc=SYSUTCDATETIME()
                       WHERE daily_progress_report_id=%s AND status='SENDING'""", (report_id,),
                )
                connection.commit()
            outcomes.append({"tenant_id": tenant_id, "status": "SENT",
                             "report_date_sast": local.date().isoformat()})
        except Exception as exc:
            logger.warning("Daily progress report generation failed", extra={
                "worker": "health_monitor", "operation": "daily_progress.generate",
                "result": type(exc).__name__,
            })
            outcomes.append({"tenant_id": tenant_id, "status": "FAILED",
                             "failure_code": type(exc).__name__})
    return outcomes
