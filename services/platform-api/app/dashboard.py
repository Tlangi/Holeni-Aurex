from decimal import Decimal

from app.config import Settings
from app.database import open_database


def _money(value: Decimal | None) -> str:
    return format(value or Decimal("0"), ".2f")


def read_dashboard(settings: Settings, tenant_id: str) -> dict[str, object]:
    """Return the owner dashboard projection in ZAR without exposing SQL details."""

    empty_portfolio: dict[str, object] = {
        "currency": settings.reporting_currency,
        "equity": "0.00",
        "balance": "0.00",
        "available_funds": "0.00",
        "margin_used": "0.00",
        "profit_loss": "0.00",
        "observed_at_utc": None,
        "conversion": None,
        "source_equity": "0.00",
        "source_balance": "0.00",
        "source_available_funds": "0.00",
        "source_margin_used": "0.00",
        "source_profit_loss": "0.00",
    }

    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT component_code, display_name, status, status_detail, checked_at_utc
            FROM app.platform_components
            ORDER BY component_code;
            """
        )
        components = [
            {
                "code": row[0],
                "name": row[1],
                "status": row[2],
                "detail": row[3],
                "checked_at_utc": row[4].isoformat() + "Z",
            }
            for row in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT TOP (1)
                equity, balance, available_funds, margin_used, profit_loss,
                source_currency, reporting_currency, conversion_rate,
                conversion_source, conversion_observed_at_utc, observed_at_utc
            FROM app.account_snapshots
            WHERE tenant_id=%s
            ORDER BY observed_at_utc DESC;
            """,
            (tenant_id,),
        )
        snapshot = cursor.fetchone()
        portfolio = empty_portfolio
        if snapshot:
            conversion_rate = snapshot[7]
            source_value = lambda value: _money(value / conversion_rate) if conversion_rate else "0.00"
            portfolio = {
                "currency": snapshot[6],
                "equity": _money(snapshot[0]),
                "balance": _money(snapshot[1]),
                "available_funds": _money(snapshot[2]),
                "margin_used": _money(snapshot[3]),
                "profit_loss": _money(snapshot[4]),
                "observed_at_utc": snapshot[10].isoformat() + "Z",
                "source_equity": source_value(snapshot[0]),
                "source_balance": source_value(snapshot[1]),
                "source_available_funds": source_value(snapshot[2]),
                "source_margin_used": source_value(snapshot[3]),
                "source_profit_loss": source_value(snapshot[4]),
                "conversion": {
                    "source_currency": snapshot[5],
                    "rate": str(snapshot[7]),
                    "source": snapshot[8],
                    "observed_at_utc": snapshot[9].isoformat() + "Z",
                },
            }

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM app.positions
            WHERE tenant_id=%s
              AND status IN ('OPEN', 'CLOSING', 'BROKER_MISSING', 'RECONCILING',
                             'RECONCILIATION_REQUIRED');
            """,
            (tenant_id,),
        )
        open_positions = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT TOP (1) account_name, external_account_id_masked, account_currency
            FROM app.trading_accounts
            WHERE tenant_id=%s
            ORDER BY created_at_utc;
            """,
            (tenant_id,),
        )
        account_row = cursor.fetchone()
        account = (
            {
                "name": account_row[0],
                "masked_id": account_row[1],
                "source_currency": account_row[2],
                "environment": "demo",
            }
            if account_row
            else None
        )

        cursor.execute(
            """
            SELECT TOP (90) equity, observed_at_utc
            FROM app.account_snapshots
            WHERE tenant_id=%s
            ORDER BY observed_at_utc DESC;
            """,
            (tenant_id,),
        )
        performance = [
            {"equity": _money(row[0]), "observed_at_utc": row[1].isoformat() + "Z"}
            for row in reversed(cursor.fetchall())
        ]

        cursor.execute(
            """
            SELECT market_symbol, direction, size, entry_price, current_price,
                   unrealised_pnl, pnl_currency, status
            FROM app.positions
            WHERE tenant_id=%s
              AND status IN ('OPEN', 'CLOSING', 'BROKER_MISSING', 'RECONCILING',
                             'RECONCILIATION_REQUIRED')
            ORDER BY opened_at_utc DESC;
            """,
            (tenant_id,),
        )
        positions = [
            {
                "market": row[0],
                "direction": row[1],
                "size": str(row[2]),
                "entry_price": str(row[3]),
                "current_price": str(row[4]) if row[4] is not None else None,
                "profit_loss": _money(row[5]),
                "currency": row[6],
                "status": row[7],
            }
            for row in cursor.fetchall()
        ]

    return {
        "locale": settings.app_locale,
        "timezone": settings.app_timezone,
        "reporting_currency": settings.reporting_currency,
        "data_status": "current" if snapshot else "awaiting_ig_sync",
        "portfolio": portfolio,
        "account": account,
        "open_positions": open_positions,
        "positions": positions,
        "performance": performance,
        "components": components,
        "safety": {
            "trading_mode": settings.trading_mode,
            "broker_environment": settings.broker_environment,
            "live_trading_allowed": False,
        },
    }


def dashboard_unavailable_payload(settings: Settings) -> dict[str, object]:
    return {
        "status": "unavailable",
        "message": "Dashboard data is not ready. Check the database migration and readiness endpoint.",
        "reporting_currency": settings.reporting_currency,
    }
