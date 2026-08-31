from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.ig_demo import CurrencyRate, IGAccount


def _converted(amount: Decimal, rate: CurrencyRate) -> Decimal:
    return (amount * rate.rate).quantize(Decimal("0.000001"))


def risk_return_percentages(
    opening_equity: Decimal, current_equity: Decimal, peak_equity: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return opening drawdown, daily return, peak return and peak drawdown.

    Inputs must all use the broker account's source currency. Reporting FX must
    never change these risk decisions.
    """
    if opening_equity <= 0 or peak_equity <= 0:
        zero = Decimal("0")
        return zero, zero, zero, zero
    opening_drawdown = max(
        Decimal("0"), (opening_equity - current_equity) / opening_equity * Decimal("100"),
    )
    daily_return = (current_equity - opening_equity) / opening_equity * Decimal("100")
    peak_return = (peak_equity - opening_equity) / opening_equity * Decimal("100")
    peak_drawdown = max(
        Decimal("0"), (peak_equity - current_equity) / peak_equity * Decimal("100"),
    )
    return opening_drawdown, daily_return, peak_return, peak_drawdown


def refresh_daily_risk_ledger(
    cursor: object, *, tenant_id: str, trading_account_id: str, account: IGAccount,
    conversion: CurrencyRate, observed_at: datetime,
) -> None:
    local_zone = ZoneInfo("Africa/Johannesburg")
    local_date = observed_at.astimezone(local_zone).date()
    day_start = datetime.combine(local_date, time.min, tzinfo=local_zone).astimezone(timezone.utc)
    day_end = datetime.combine(local_date, time.max, tzinfo=local_zone).astimezone(timezone.utc)
    current_equity = _converted(account.equity, conversion)
    current_equity_source = account.equity
    unrealized = _converted(account.profit_loss, conversion)
    cursor.execute(
        """SELECT TOP (1) equity,source_equity FROM app.account_snapshots
           WHERE trading_account_id=%s AND observed_at_utc>=%s AND observed_at_utc<=%s
           ORDER BY observed_at_utc""",
        (trading_account_id, day_start, day_end),
    )
    first = cursor.fetchone()
    opening_equity = Decimal(str(first[0])) if first else current_equity
    opening_equity_source = Decimal(str(first[1])) if first and first[1] is not None else current_equity_source
    cursor.execute(
        """SELECT MAX(equity) FROM app.account_snapshots
           WHERE trading_account_id=%s AND observed_at_utc>=%s AND observed_at_utc<=%s""",
        (trading_account_id, day_start, day_end),
    )
    peak_row = cursor.fetchone()
    peak_equity = max(opening_equity, current_equity, Decimal(str(peak_row[0] or 0)))
    cursor.execute(
        """SELECT MAX(source_equity) FROM app.account_snapshots
           WHERE trading_account_id=%s AND observed_at_utc>=%s AND observed_at_utc<=%s""",
        (trading_account_id, day_start, day_end),
    )
    peak_source_row = cursor.fetchone()
    peak_equity_source = max(
        opening_equity_source, current_equity_source,
        Decimal(str(peak_source_row[0] or 0)),
    )
    cursor.execute(
        """SELECT COALESCE(SUM(risk_amount_zar),0) FROM app.order_intents
           WHERE trading_account_id=%s AND status IN
             ('CREATED','RISK_APPROVED','SUBMITTING','SUBMITTED','CONFIRMING','OPEN',
              'SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED')""",
        (trading_account_id,),
    )
    reserved_risk = Decimal(str(cursor.fetchone()[0] or 0))
    drawdown, daily_return, peak_return, intraday_drawdown = risk_return_percentages(
        opening_equity_source, current_equity_source, peak_equity_source,
    )
    cursor.execute(
        """SELECT TOP (1) daily_loss_limit_pct,max_intraday_drawdown_pct,
                  profit_protection_pct,daily_profit_lock_pct,profit_giveback_limit_pct
           FROM app.risk_versions
           WHERE tenant_id=%s AND active=1""",
        (tenant_id,),
    )
    policy = cursor.fetchone()
    limit = Decimal(str(policy[0])) if policy else Decimal("0")
    intraday_limit = Decimal(str(policy[1])) if policy else Decimal("0")
    protect_at = Decimal(str(policy[2])) if policy else Decimal("0")
    lock_at = Decimal(str(policy[3])) if policy else Decimal("0")
    giveback_limit = Decimal(str(policy[4])) if policy else Decimal("0")
    giveback_pct = ((peak_return - daily_return) / peak_return * Decimal("100")) if peak_return > 0 else Decimal("0")
    protection_state = (
        "DAILY_GAIN_LOCKED" if daily_return >= lock_at else
        "PROFIT_PROTECTION" if peak_return >= protect_at else "NORMAL"
    )
    reason = None
    if not policy:
        reason = "NO_ACTIVE_RISK_POLICY"
    elif drawdown >= limit:
        reason = "DAILY_LOSS_LIMIT"
    elif intraday_drawdown >= intraday_limit:
        reason = "INTRADAY_DRAWDOWN_LIMIT"
    elif daily_return >= lock_at:
        reason = "DAILY_PROFIT_LOCK"
    elif peak_return >= protect_at and giveback_pct >= giveback_limit:
        reason = "PROFIT_GIVEBACK_LIMIT"
    status = "BLOCKED" if reason else "CURRENT"
    cursor.execute(
        """MERGE app.daily_risk_ledger AS target
           USING (SELECT %s trading_account_id,%s ledger_date_sast) AS source
             ON target.trading_account_id=source.trading_account_id
            AND target.ledger_date_sast=source.ledger_date_sast
           WHEN MATCHED THEN UPDATE SET current_equity_zar=%s,unrealized_pnl_zar=%s,
             reserved_risk_zar=%s,daily_drawdown_pct=%s,peak_equity_zar=%s,
             intraday_drawdown_pct=%s,daily_return_pct=%s,peak_daily_return_pct=%s,
             profit_protection_state=%s,opening_equity_source=%s,current_equity_source=%s,
             peak_equity_source=%s,source_currency=%s,risk_return_basis='SOURCE_CURRENCY',
             status=%s,status_reason=%s,
             last_reconciled_at_utc=%s,updated_at_utc=SYSUTCDATETIME()
           WHEN NOT MATCHED THEN INSERT
             (daily_risk_ledger_id,tenant_id,trading_account_id,ledger_date_sast,
              opening_equity_zar,current_equity_zar,unrealized_pnl_zar,reserved_risk_zar,
              daily_drawdown_pct,peak_equity_zar,intraday_drawdown_pct,daily_return_pct,
              peak_daily_return_pct,profit_protection_state,opening_equity_source,
              current_equity_source,peak_equity_source,source_currency,risk_return_basis,
              status,status_reason,last_reconciled_at_utc)
           VALUES(%s,%s,source.trading_account_id,source.ledger_date_sast,%s,%s,%s,%s,%s,%s,
                  %s,%s,%s,%s,%s,%s,%s,%s,'SOURCE_CURRENCY',%s,%s,%s);""",
        (
            trading_account_id, local_date, current_equity, unrealized, reserved_risk,
            drawdown, peak_equity, intraday_drawdown, daily_return, peak_return, protection_state,
            opening_equity_source, current_equity_source, peak_equity_source, account.currency,
            status, reason, observed_at, str(uuid4()), tenant_id,
            opening_equity, current_equity, unrealized, reserved_risk, drawdown,
            peak_equity, intraday_drawdown, daily_return, peak_return, protection_state,
            opening_equity_source, current_equity_source, peak_equity_source, account.currency,
            status, reason, observed_at,
        ),
    )
