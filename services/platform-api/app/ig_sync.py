from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parseaddr
from hashlib import sha256
import json
import logging
from threading import Lock
from time import perf_counter
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.ig_demo import CurrencyRate, IGAccount, IGDemoClient
from app.risk_ledger import refresh_daily_risk_ledger
from app.order_lifecycle import transition_intent

_process_sync_lock = Lock()
logger = logging.getLogger("aurex.sync")


class SyncAlreadyRunning(RuntimeError):
    pass


def _converted(amount: Decimal, rate: CurrencyRate) -> Decimal:
    return (amount * rate.rate).quantize(Decimal("0.000001"))


def _owner_email(settings: Settings) -> str:
    configured = settings.owner_email or settings.smtp_from_email or settings.smtp_username
    return parseaddr(configured)[1].strip().lower()


def sync_ig_demo(settings: Settings, *, correlation_id: str | None = None) -> dict[str, object]:
    """Read IG demo state and persist one atomic, auditable ZAR snapshot."""
    if not _process_sync_lock.acquire(blocking=False):
        raise SyncAlreadyRunning("An IG synchronisation is already running")
    started_clock = perf_counter()
    observed_at = datetime.now(timezone.utc)
    correlation_id = correlation_id or str(uuid4())
    sync_run_id = str(uuid4())
    account: IGAccount
    positions: list[dict[str, object]]
    working_orders: list[dict[str, object]]
    conversion: CurrencyRate
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                DECLARE @lock_result int;
                EXEC @lock_result = sys.sp_getapplock
                    @Resource='aurex:ig-demo-sync', @LockMode='Exclusive',
                    @LockOwner='Session', @LockTimeout=0;
                SELECT @lock_result;
                """
            )
            if int(cursor.fetchone()[0]) < 0:
                raise SyncAlreadyRunning("Another worker owns the IG synchronisation lock")
            cursor.execute(
                """
                INSERT INTO app.sync_runs
                    (sync_run_id, correlation_id, worker, status, started_at_utc)
                VALUES (%s, %s, 'account_sync', 'RUNNING', %s);
                """,
                (sync_run_id, correlation_id, observed_at),
            )
            connection.commit()

            try:
                with IGDemoClient(settings) as client:
                    account = client.account()
                    positions = client.positions()
                    working_orders = client.working_orders()
                    conversion = client.zar_rate(account.currency)
                tenant_id = _ensure_tenant(cursor, settings)
                _ensure_owner(cursor, tenant_id, settings)
                broker_connection_id = _ensure_broker_connection(cursor, tenant_id, account)
                trading_account_id = _ensure_trading_account(
                    cursor, tenant_id, broker_connection_id, account
                )
                _store_rate(cursor, conversion)
                fingerprint = _snapshot_fingerprint(account, conversion, positions)
                snapshot_created = _store_snapshot(
                    cursor,
                    tenant_id,
                    trading_account_id,
                    account,
                    conversion,
                    observed_at,
                    fingerprint,
                )
                _store_positions(
                    cursor,
                    tenant_id,
                    trading_account_id,
                    positions,
                    account.currency,
                    correlation_id,
                )
                _store_working_orders(cursor, tenant_id, trading_account_id, working_orders)
                _reconcile_order_state(cursor, tenant_id, trading_account_id)
                refresh_daily_risk_ledger(
                    cursor,
                    tenant_id=tenant_id,
                    trading_account_id=trading_account_id,
                    account=account,
                    conversion=conversion,
                    observed_at=observed_at,
                )
                _update_components(cursor, observed_at)
                cursor.execute(
                    """
                    INSERT INTO app.audit_logs
                        (tenant_id, action_code, entity_type, entity_id, correlation_id, metadata_json)
                    VALUES (%s, 'ig.demo.sync', 'trading_account', %s, %s,
                            N'{"source":"ig_demo","reporting_currency":"ZAR"}');
                    """,
                    (tenant_id, trading_account_id, correlation_id),
                )
                duration_ms = round((perf_counter() - started_clock) * 1000)
                cursor.execute(
                    """
                    UPDATE app.sync_runs
                    SET tenant_id=%s, broker_connection_id=%s, trading_account_id=%s,
                        status='SUCCESS', positions_seen=%s, snapshot_created=%s,
                        completed_at_utc=SYSUTCDATETIME(), duration_ms=%s
                    WHERE sync_run_id=%s;
                    """,
                    (
                        tenant_id,
                        broker_connection_id,
                        trading_account_id,
                        len(positions),
                        snapshot_created,
                        duration_ms,
                        sync_run_id,
                    ),
                )
                connection.commit()
                logger.info(
                    "IG demo synchronisation completed",
                    extra={
                        "correlation_id": correlation_id,
                        "tenant_id": tenant_id,
                        "trading_account_id": trading_account_id,
                        "broker_connection_id": broker_connection_id,
                        "worker": "account_sync",
                        "operation": "ig.sync",
                        "duration_ms": duration_ms,
                        "result": "SUCCESS",
                    },
                )
            except Exception as exc:
                connection.rollback()
                duration_ms = round((perf_counter() - started_clock) * 1000)
                cursor.execute(
                    """
                    UPDATE app.sync_runs
                    SET status='FAILED', error_code=%s,
                        completed_at_utc=SYSUTCDATETIME(), duration_ms=%s
                    WHERE sync_run_id=%s;
                    """,
                    (type(exc).__name__[:80], duration_ms, sync_run_id),
                )
                cursor.execute(
                    """
                    UPDATE app.platform_components
                    SET status='DEGRADED', status_detail=N'IG account synchronisation failed',
                        checked_at_utc=SYSUTCDATETIME()
                    WHERE component_code IN ('ig_demo', 'market_feed');
                    """
                )
                connection.commit()
                logger.warning(
                    "IG demo synchronisation failed",
                    extra={
                        "correlation_id": correlation_id,
                        "worker": "account_sync",
                        "operation": "ig.sync",
                        "duration_ms": duration_ms,
                        "result": type(exc).__name__,
                    },
                )
                raise
            finally:
                cursor.execute(
                    "EXEC sys.sp_releaseapplock @Resource='aurex:ig-demo-sync', @LockOwner='Session';"
                )
                connection.commit()
    finally:
        _process_sync_lock.release()

    return {
        "status": "synchronised",
        "message": "IG demo synchronisation completed",
        "account": account.masked_account_id,
        "source_currency": account.currency,
        "reporting_currency": "ZAR",
        "conversion_source": conversion.source,
        "conversion_observed_at_utc": conversion.observed_at_utc.isoformat(),
        "open_positions": len(positions),
        "working_orders": len(working_orders),
        "observed_at_utc": observed_at.isoformat(),
        "execution_enabled": False,
    }


def _store_working_orders(cursor: object, tenant_id: str, trading_account_id: str,
                          orders: list[dict[str, object]]) -> None:
    seen: set[str] = set()
    for item in orders:
        order = item.get("workingOrderData") or item.get("workingOrder") or item
        market = item.get("marketData") or item.get("market") or {}
        deal_id = str(order.get("dealId") or "")
        if not deal_id:
            continue
        seen.add(deal_id)
        cursor.execute(
            """MERGE app.broker_working_orders AS target
               USING (SELECT %s trading_account_id,%s broker_deal_id) source
               ON target.trading_account_id=source.trading_account_id
               AND target.broker_deal_id=source.broker_deal_id
               WHEN MATCHED THEN UPDATE SET deal_reference=%s,epic=%s,direction=%s,size=%s,
                 level=%s,status='OPEN',last_seen_at_utc=SYSUTCDATETIME()
               WHEN NOT MATCHED THEN INSERT
                 (broker_working_order_id,tenant_id,trading_account_id,broker_deal_id,
                  deal_reference,epic,direction,size,level,status)
                 VALUES(NEWID(),%s,source.trading_account_id,source.broker_deal_id,
                        %s,%s,%s,%s,%s,'OPEN');""",
            (trading_account_id, deal_id, order.get("dealReference"),
             market.get("epic") or order.get("epic"), order.get("direction"),
             order.get("orderSize") or order.get("size"), order.get("orderLevel") or order.get("level"),
             tenant_id, order.get("dealReference"), market.get("epic") or order.get("epic"),
             order.get("direction"), order.get("orderSize") or order.get("size"),
             order.get("orderLevel") or order.get("level")),
        )
    if seen:
        placeholders = ",".join(["%s"] * len(seen))
        cursor.execute(
            f"""UPDATE app.broker_working_orders SET status='MISSING',last_seen_at_utc=SYSUTCDATETIME()
                WHERE trading_account_id=%s AND status='OPEN' AND broker_deal_id NOT IN ({placeholders})""",
            (trading_account_id, *sorted(seen)),
        )
    else:
        cursor.execute("UPDATE app.broker_working_orders SET status='MISSING',last_seen_at_utc=SYSUTCDATETIME() WHERE trading_account_id=%s AND status='OPEN'",
                       (trading_account_id,))


def _reconcile_order_state(cursor: object, tenant_id: str, trading_account_id: str) -> None:
    """Compare local submissions with both broker positions and working orders."""
    issue_types = (
        "UNKNOWN_WORKING_ORDER", "STALE_LOCAL_SUBMISSION",
        "DUPLICATE_DEAL_REFERENCE", "SUBMISSION_UNKNOWN",
    )
    placeholders = ",".join(["%s"] * len(issue_types))
    cursor.execute(
        f"""UPDATE app.reconciliation_issues SET status='RESOLVED',
               resolved_at_utc=SYSUTCDATETIME(),last_seen_at_utc=SYSUTCDATETIME()
             WHERE trading_account_id=%s AND status IN ('OPEN','INVESTIGATING')
               AND issue_type IN ({placeholders})""",
        (trading_account_id, *issue_types),
    )
    cursor.execute(
        """SELECT w.deal_reference,w.broker_deal_id FROM app.broker_working_orders w
             WHERE w.trading_account_id=%s AND w.status='OPEN'
               AND NOT EXISTS(SELECT 1 FROM app.order_intents oi
                 WHERE oi.trading_account_id=w.trading_account_id
                   AND (oi.client_reference=w.deal_reference
                     OR oi.broker_deal_reference=w.broker_deal_id))""",
        (trading_account_id,),
    )
    for reference, deal_id in cursor.fetchall():
        _record_account_issue(cursor, tenant_id, trading_account_id,
                              "UNKNOWN_WORKING_ORDER", str(reference or deal_id or ""),
                              "Broker working order has no matching Aurex order intent")
    cursor.execute(
        """SELECT reference_value FROM (
               SELECT broker_deal_reference reference_value FROM app.order_intents
                 WHERE trading_account_id=%s AND broker_deal_reference IS NOT NULL
               UNION ALL
               SELECT deal_reference FROM app.broker_working_orders
                 WHERE trading_account_id=%s AND status='OPEN' AND deal_reference IS NOT NULL
             ) refs GROUP BY reference_value HAVING COUNT(*)>1""",
        (trading_account_id, trading_account_id),
    )
    for row in cursor.fetchall():
        _record_account_issue(cursor, tenant_id, trading_account_id,
                              "DUPLICATE_DEAL_REFERENCE", str(row[0]),
                              "Deal reference is duplicated across local or broker state")
    cursor.execute(
        """SELECT oi.client_reference,oi.status FROM app.order_intents oi
             WHERE oi.trading_account_id=%s
               AND oi.status IN ('SUBMITTING','SUBMITTED','CONFIRMING','RECONCILIATION_REQUIRED')
               AND oi.updated_at_utc<DATEADD(minute,-5,SYSUTCDATETIME())
               AND NOT EXISTS(SELECT 1 FROM app.positions p
                 WHERE p.trading_account_id=oi.trading_account_id
                   AND (p.order_intent_id=oi.order_intent_id OR p.broker_deal_id=oi.broker_deal_reference)
                   AND p.status<>'CLOSED')
               AND NOT EXISTS(SELECT 1 FROM app.broker_working_orders w
                 WHERE w.trading_account_id=oi.trading_account_id AND w.status='OPEN'
                   AND (w.deal_reference=oi.client_reference OR w.broker_deal_id=oi.broker_deal_reference))""",
        (trading_account_id,),
    )
    for reference, state in cursor.fetchall():
        _record_account_issue(cursor, tenant_id, trading_account_id,
                              "STALE_LOCAL_SUBMISSION", str(reference),
                              f"Local order intent remains {state} without broker evidence")
    cursor.execute(
        """SELECT client_reference FROM app.order_intents
             WHERE trading_account_id=%s AND status='SUBMISSION_UNKNOWN'""",
        (trading_account_id,),
    )
    for row in cursor.fetchall():
        _record_account_issue(cursor, tenant_id, trading_account_id,
                              "SUBMISSION_UNKNOWN", str(row[0]),
                              "Submission outcome is ambiguous; automatic retry is prohibited")


def _record_account_issue(cursor: object, tenant_id: str, trading_account_id: str,
                          issue_type: str, reference: str, detail: str) -> None:
    masked = f"••••{reference[-4:]}" if reference else None
    cursor.execute(
        """SELECT reconciliation_issue_id FROM app.reconciliation_issues
             WHERE trading_account_id=%s AND issue_type=%s AND broker_reference_masked=%s
               AND status IN ('OPEN','INVESTIGATING')""",
        (trading_account_id, issue_type, masked),
    )
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE app.reconciliation_issues SET last_seen_at_utc=SYSUTCDATETIME(),detail=%s WHERE reconciliation_issue_id=%s",
                       (detail, str(row[0])))
        return
    cursor.execute(
        """INSERT app.reconciliation_issues
             (reconciliation_issue_id,tenant_id,trading_account_id,position_id,issue_type,status,
              broker_reference_masked,detail,first_seen_at_utc,last_seen_at_utc)
             VALUES(%s,%s,%s,NULL,%s,'OPEN',%s,%s,SYSUTCDATETIME(),SYSUTCDATETIME())""",
        (str(uuid4()), tenant_id, trading_account_id, issue_type, masked, detail),
    )


def _snapshot_fingerprint(
    account: IGAccount, conversion: CurrencyRate, positions: list[dict[str, object]]
) -> str:
    position_state = []
    for item in positions:
        position = item.get("position") or {}
        market = item.get("market") or {}
        position_state.append(
            {
                "deal_id": position.get("dealId"),
                "profit": position.get("profit"),
                "bid": market.get("bid"),
                "offer": market.get("offer"),
            }
        )
    payload = {
        "account": account.account_id,
        "balance": str(account.balance),
        "profit_loss": str(account.profit_loss),
        "available": str(account.available),
        "margin": str(account.margin_used),
        "rate": str(conversion.rate),
        "positions": sorted(position_state, key=lambda item: str(item["deal_id"])),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _ensure_tenant(cursor: object, settings: Settings) -> str:
    cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc;")
    row = cursor.fetchone()
    if row:
        return str(row[0])
    tenant_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO app.tenants
            (tenant_id, tenant_name, country_code, reporting_currency, time_zone_id)
        VALUES (%s, %s, 'ZA', 'ZAR', %s);
        """,
        (tenant_id, f"{settings.owner_display_name} trading", settings.app_timezone),
    )
    return tenant_id


def _ensure_owner(cursor: object, tenant_id: str, settings: Settings) -> None:
    email = _owner_email(settings)
    if not email:
        return
    cursor.execute(
        "SELECT user_id FROM app.users WHERE tenant_id=%s AND email=%s;", (tenant_id, email)
    )
    if cursor.fetchone():
        return
    cursor.execute(
        """
        INSERT INTO app.users (user_id, tenant_id, email, display_name, role, status)
        VALUES (%s, %s, %s, %s, 'owner', 'active');
        """,
        (str(uuid4()), tenant_id, email, settings.owner_display_name),
    )


def _ensure_broker_connection(cursor: object, tenant_id: str, account: IGAccount) -> str:
    cursor.execute(
        """
        SELECT broker_connection_id
        FROM app.broker_connections
        WHERE tenant_id=%s AND broker_code='IG' AND environment='demo';
        """,
        (tenant_id,),
    )
    row = cursor.fetchone()
    if row:
        broker_id = str(row[0])
        cursor.execute(
            """
            UPDATE app.broker_connections
            SET status='connected', account_currency=%s,
                external_account_id_masked=%s, last_authenticated_at_utc=SYSUTCDATETIME(),
                updated_at_utc=SYSUTCDATETIME()
            WHERE broker_connection_id=%s;
            """,
            (account.currency, account.masked_account_id, broker_id),
        )
        return broker_id
    broker_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO app.broker_connections
            (broker_connection_id, tenant_id, broker_code, environment,
             external_account_id_masked, secret_reference, status, account_currency,
             last_authenticated_at_utc)
        VALUES (%s, %s, 'IG', 'demo', %s, 'environment:platform-api',
                'connected', %s, SYSUTCDATETIME());
        """,
        (broker_id, tenant_id, account.masked_account_id, account.currency),
    )
    return broker_id


def _ensure_trading_account(
    cursor: object, tenant_id: str, broker_id: str, account: IGAccount
) -> str:
    cursor.execute(
        "SELECT trading_account_id FROM app.trading_accounts WHERE broker_connection_id=%s;",
        (broker_id,),
    )
    row = cursor.fetchone()
    if row:
        return str(row[0])
    account_id = str(uuid4())
    cursor.execute(
        """
        INSERT INTO app.trading_accounts
            (trading_account_id, tenant_id, broker_connection_id, account_name,
             external_account_id_masked, account_currency, reporting_currency, trading_enabled)
        VALUES (%s, %s, %s, %s, %s, %s, 'ZAR', 0);
        """,
        (
            account_id,
            tenant_id,
            broker_id,
            account.account_name,
            account.masked_account_id,
            account.currency,
        ),
    )
    return account_id


def _store_rate(cursor: object, rate: CurrencyRate) -> None:
    if rate.base_currency == rate.quote_currency:
        return
    cursor.execute(
        """
        IF NOT EXISTS
        (
            SELECT 1 FROM app.fx_rates
            WHERE base_currency=%s AND quote_currency=%s AND source=%s
              AND observed_at_utc=%s
        )
        INSERT INTO app.fx_rates
            (base_currency, quote_currency, rate, source, observed_at_utc)
        VALUES (%s, %s, %s, %s, %s);
        """,
        (
            rate.base_currency,
            rate.quote_currency,
            rate.source,
            rate.observed_at_utc,
            rate.base_currency,
            rate.quote_currency,
            rate.rate,
            rate.source,
            rate.observed_at_utc,
        ),
    )


def _store_snapshot(
    cursor: object,
    tenant_id: str,
    trading_account_id: str,
    account: IGAccount,
    rate: CurrencyRate,
    observed_at: datetime,
    fingerprint: str,
) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM app.account_snapshots
        WHERE trading_account_id=%s AND snapshot_fingerprint=%s;
        """,
        (trading_account_id, fingerprint),
    )
    if cursor.fetchone():
        return False
    cursor.execute(
        """
        INSERT INTO app.account_snapshots
            (tenant_id, trading_account_id, equity, balance, available_funds,
             margin_used, profit_loss, source_currency, reporting_currency,
             conversion_rate, conversion_source, conversion_observed_at_utc,
             observed_at_utc, snapshot_fingerprint,source_equity,source_balance,
             source_available_funds,source_margin_used,source_profit_loss)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ZAR', %s, %s, %s, %s, %s,
                %s,%s,%s,%s,%s);
        """,
        (
            tenant_id,
            trading_account_id,
            _converted(account.equity, rate),
            _converted(account.balance, rate),
            _converted(account.available, rate),
            _converted(account.margin_used, rate),
            _converted(account.profit_loss, rate),
            account.currency,
            rate.rate,
            rate.source,
            rate.observed_at_utc,
            observed_at,
            fingerprint,
            account.equity,
            account.balance,
            account.available,
            account.margin_used,
            account.profit_loss,
        ),
    )
    return True


def _store_positions(
    cursor: object,
    tenant_id: str,
    trading_account_id: str,
    positions: list[dict[str, object]],
    account_currency: str,
    correlation_id: str,
) -> None:
    seen_deals: set[str] = set()
    for item in positions:
        position = item.get("position") or {}
        market = item.get("market") or {}
        deal_id = str(position.get("dealId") or "")
        if not deal_id:
            continue
        seen_deals.add(deal_id)
        matched_intent = _matched_order_intent(cursor, trading_account_id, position)
        opened = position.get("createdDateUTC") or position.get("createdDate")
        cursor.execute(
            """SELECT position_id,status,origin,order_intent_id FROM app.positions
               WHERE trading_account_id=%s AND broker_deal_id=%s;""",
            (trading_account_id, deal_id),
        )
        existing = cursor.fetchone()
        if existing:
            unresolved_discovery = existing[2] == "BROKER_DISCOVERED" and existing[3] is None and not matched_intent
            next_status = "RECONCILIATION_REQUIRED" if unresolved_discovery else "OPEN"
            cursor.execute(
                """
                UPDATE app.positions
                SET current_price=%s, unrealised_pnl=%s, status=%s,
                    order_intent_id=COALESCE(%s,order_intent_id),
                    origin=CASE WHEN %s IS NOT NULL THEN 'AUREX_ORDER' ELSE origin END,
                    broker_missing_at_utc=NULL, reconciliation_attempts=0,
                    updated_at_utc=SYSUTCDATETIME()
                WHERE position_id=%s;
                """,
                (market.get("bid") or market.get("offer"), position.get("profit"), next_status,
                 str(matched_intent["order_intent_id"]) if matched_intent else None,
                 str(matched_intent["order_intent_id"]) if matched_intent else None, str(existing[0])),
            )
            if unresolved_discovery:
                _upsert_reconciliation_issue(
                    cursor, tenant_id, trading_account_id, str(existing[0]), deal_id,
                )
            elif matched_intent:
                _resolve_reconciliation_issues(cursor, str(existing[0]))
                _advance_intent_to_open(cursor, matched_intent, correlation_id, deal_id)
            elif existing[1] != "OPEN":
                _position_event(
                    cursor,
                    str(existing[0]),
                    "BROKER_POSITION_RECOVERED",
                    existing[1],
                    "OPEN",
                    correlation_id,
                )
        else:
            position_id = str(uuid4())
            cursor.execute(
                """
                INSERT INTO app.positions
                    (position_id, tenant_id, trading_account_id, broker_deal_id,
                     market_symbol, direction, size, entry_price, current_price,
                     stop_price, limit_price, unrealised_pnl, pnl_currency,
                     status, opened_at_utc, origin, order_intent_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, COALESCE(TRY_CONVERT(datetime2(3), %s), SYSUTCDATETIME()),
                        %s,%s);
                """,
                (
                    position_id,
                    tenant_id,
                    trading_account_id,
                    deal_id,
                    market.get("instrumentName") or market.get("epic") or "Unknown",
                    position.get("direction"),
                    position.get("dealSize") or position.get("size") or 0,
                    position.get("level") or 0,
                    market.get("bid") or market.get("offer"),
                    position.get("stopLevel"),
                    position.get("limitLevel"),
                    position.get("profit"),
                    position.get("currency") or account_currency,
                    "OPEN" if matched_intent else "RECONCILIATION_REQUIRED",
                    opened,
                    "AUREX_ORDER" if matched_intent else "BROKER_DISCOVERED",
                    str(matched_intent["order_intent_id"]) if matched_intent else None,
                ),
            )
            _position_event(
                cursor,
                position_id,
                "BROKER_POSITION_DISCOVERED",
                None,
                "OPEN" if matched_intent else "RECONCILIATION_REQUIRED",
                correlation_id,
            )
            if matched_intent:
                _advance_intent_to_open(cursor, matched_intent, correlation_id, deal_id)
            else:
                _upsert_reconciliation_issue(
                    cursor, tenant_id, trading_account_id, position_id, deal_id,
                )

    cursor.execute(
        """
        SELECT position_id, broker_deal_id, status, reconciliation_attempts, origin
        FROM app.positions
        WHERE trading_account_id=%s
          AND status IN ('OPEN', 'BROKER_MISSING', 'RECONCILING','RECONCILIATION_REQUIRED');
        """,
        (trading_account_id,),
    )
    local_positions = cursor.fetchall()
    for local in local_positions:
        if local[1] in seen_deals:
            continue
        from_status = local[2]
        attempts = int(local[3])
        if from_status == "RECONCILIATION_REQUIRED" and local[4] == "BROKER_DISCOVERED":
            to_status, event_type = "CLOSED", "UNEXPECTED_BROKER_POSITION_GONE"
            cursor.execute(
                """UPDATE app.reconciliation_issues SET status='RESOLVED',
                   resolved_at_utc=SYSUTCDATETIME(),last_seen_at_utc=SYSUTCDATETIME()
                   WHERE position_id=%s AND status IN ('OPEN','INVESTIGATING')""",
                (str(local[0]),),
            )
        elif from_status == "OPEN":
            to_status, event_type = "BROKER_MISSING", "BROKER_POSITION_MISSING"
        elif from_status == "BROKER_MISSING":
            to_status, event_type = "RECONCILING", "POSITION_RECONCILIATION_STARTED"
        elif attempts >= 1:
            to_status, event_type = "CLOSED", "BROKER_CLOSURE_CONFIRMED"
        else:
            to_status, event_type = "RECONCILING", "POSITION_RECONCILIATION_RETRY"
        cursor.execute(
            """
            UPDATE app.positions
            SET status=%s,
                broker_missing_at_utc=COALESCE(broker_missing_at_utc, SYSUTCDATETIME()),
                reconciliation_attempts=reconciliation_attempts+1,
                closed_at_utc=CASE WHEN %s='CLOSED' THEN SYSUTCDATETIME() ELSE closed_at_utc END,
                updated_at_utc=SYSUTCDATETIME()
            WHERE position_id=%s;
            """,
            (to_status, to_status, str(local[0])),
        )
        _position_event(
            cursor,
            str(local[0]),
            event_type,
            from_status,
            to_status,
            correlation_id,
        )


def _position_event(
    cursor: object,
    position_id: str,
    event_type: str,
    from_status: str | None,
    to_status: str,
    correlation_id: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO app.position_events
            (position_id, event_type, from_status, to_status, broker_observed,
             correlation_id)
        VALUES (%s, %s, %s, %s, 1, %s);
        """,
        (position_id, event_type, from_status, to_status, correlation_id),
    )


def _upsert_reconciliation_issue(
    cursor: object, tenant_id: str, trading_account_id: str, position_id: str, deal_id: str,
) -> None:
    masked = f"••••{deal_id[-4:]}" if deal_id else None
    cursor.execute(
        """SELECT reconciliation_issue_id FROM app.reconciliation_issues
           WHERE position_id=%s AND issue_type='UNEXPECTED_BROKER_POSITION'
             AND status IN ('OPEN','INVESTIGATING')""",
        (position_id,),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """UPDATE app.reconciliation_issues SET last_seen_at_utc=SYSUTCDATETIME(),
               broker_reference_masked=%s WHERE reconciliation_issue_id=%s""",
            (masked, str(existing[0])),
        )
        return
    cursor.execute(
        """INSERT app.reconciliation_issues
           (reconciliation_issue_id,tenant_id,trading_account_id,position_id,issue_type,status,
            broker_reference_masked,detail,first_seen_at_utc,last_seen_at_utc)
           VALUES(%s,%s,%s,%s,'UNEXPECTED_BROKER_POSITION','OPEN',%s,
                  N'Broker position has no Aurex order intent; new entries are blocked',
                  SYSUTCDATETIME(),SYSUTCDATETIME())""",
        (str(uuid4()), tenant_id, trading_account_id, position_id, masked),
    )


def _matched_order_intent(cursor: object, trading_account_id: str, position: dict[str, object]) -> dict[str, object] | None:
    reference = str(position.get("dealReference") or "")
    if not reference:
        return None
    cursor.execute(
        """SELECT order_intent_id,status FROM app.order_intents
           WHERE trading_account_id=%s AND client_reference=%s
             AND status IN ('SUBMITTING','SUBMITTED','CONFIRMING','SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED')""",
        (trading_account_id, reference),
    )
    row = cursor.fetchone()
    return {"order_intent_id": str(row[0]), "status": str(row[1])} if row else None


def _advance_intent_to_open(
    cursor: object, intent: dict[str, object], correlation_id: str, deal_id: str,
) -> None:
    intent_id, state = str(intent["order_intent_id"]), str(intent["status"])
    if state == "SUBMITTING":
        transition_intent(cursor, intent_id, from_status=state, to_status="SUBMITTED",
                          event_type="BROKER_POSITION_MATCHED", correlation_id=correlation_id)
        state = "SUBMITTED"
    if state == "SUBMITTED":
        transition_intent(cursor, intent_id, from_status=state, to_status="CONFIRMING",
                          event_type="BROKER_CONFIRMATION_RECONCILING", correlation_id=correlation_id)
        state = "CONFIRMING"
    transition_intent(
        cursor, intent_id, from_status=state, to_status="OPEN",
        event_type="BROKER_POSITION_RECONCILED", correlation_id=correlation_id,
        details={"broker_deal_suffix": deal_id[-4:]},
    )
    cursor.execute(
        """UPDATE app.order_intents SET broker_deal_reference=%s
           WHERE order_intent_id=%s""",
        (deal_id, intent_id),
    )


def _resolve_reconciliation_issues(cursor: object, position_id: str) -> None:
    cursor.execute(
        """UPDATE app.reconciliation_issues SET status='RESOLVED',resolved_at_utc=SYSUTCDATETIME(),
           last_seen_at_utc=SYSUTCDATETIME()
           WHERE position_id=%s AND status IN ('OPEN','INVESTIGATING')""",
        (position_id,),
    )


def _update_components(cursor: object, observed_at: datetime) -> None:
    cursor.execute(
        """
        UPDATE app.platform_components
        SET status = CASE component_code
                WHEN 'ig_demo' THEN 'CURRENT'
                WHEN 'market_feed' THEN 'CURRENT'
                ELSE status END,
            status_detail = CASE component_code
                WHEN 'ig_demo' THEN N'Authenticated read-only demo connection'
                WHEN 'market_feed' THEN N'IG REST account data is current'
                ELSE status_detail END,
            checked_at_utc=%s
        WHERE component_code IN ('ig_demo', 'market_feed');
        """,
        (observed_at,),
    )
