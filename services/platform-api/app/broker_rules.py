from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config import Settings
from app.database import open_database
from app.ig_demo import IGDemoClient

logger = logging.getLogger("aurex.broker_rules")


def sync_broker_market_rules(
    settings: Settings, *, client: IGDemoClient | None = None, force: bool = False
) -> dict[str, object]:
    """Synchronize risk-sizing rules without exposing any order capability."""
    owned_client = client is None
    if owned_client and not force:
        current = _current_rule_symbols(settings)
        if len(current) == _enabled_market_count(settings):
            return {
                "status": "completed",
                "markets": [{"symbol": symbol, "result": "CURRENT"} for symbol in current],
                "execution_enabled": False,
            }
    ig = client or IGDemoClient(settings)
    if owned_client:
        ig.authenticate()
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(
                """SELECT TOP (1) bc.broker_connection_id
                   FROM app.broker_connections bc
                   WHERE bc.broker_code='IG' AND bc.environment='demo'
                   ORDER BY bc.created_at_utc"""
            )
            broker = cursor.fetchone()
            if not broker:
                raise ValueError("No synchronized IG demo broker connection exists")
            cursor.execute(
                """SELECT m.market_id,m.symbol,m.ig_epic,m.quote_currency,r.observed_at_utc
                   FROM app.markets m
                   LEFT JOIN app.broker_market_rules r
                     ON r.market_id=m.market_id AND r.broker_connection_id=%s
                   WHERE m.enabled=1 ORDER BY m.symbol""",
                (str(broker["broker_connection_id"]),),
            )
            markets = cursor.fetchall()
            observed = datetime.now(timezone.utc)
            outcomes: list[dict[str, object]] = []
            currency_rates: dict[str, Decimal] = {}
            for market in markets:
                previous = market.get("observed_at_utc")
                if not force and previous and previous.replace(tzinfo=timezone.utc) >= observed - timedelta(minutes=15):
                    outcomes.append({"symbol": market["symbol"], "result": "CURRENT"})
                    continue
                quote = str(market["quote_currency"])
                if quote not in currency_rates:
                    currency_rates[quote] = ig.zar_rate(quote).rate
                rule = ig.broker_market_rule(
                    str(market["ig_epic"]),
                    quote_currency=quote,
                    quote_to_zar=currency_rates[quote],
                )
                cursor.execute(
                    """MERGE app.broker_market_rules AS target
                       USING (SELECT %s broker_connection_id,%s market_id) AS source
                         ON target.broker_connection_id=source.broker_connection_id
                        AND target.market_id=source.market_id
                       WHEN MATCHED THEN UPDATE SET
                         min_deal_size=%s,size_increment=%s,min_stop_distance=%s,
                         value_per_price_point_zar=%s,source_currency=%s,observed_at_utc=%s,
                         stop_distance_unit=%s,lot_size=%s,market_status=%s,
                         deal_currency=%s,expiry=%s,force_open_allowed=%s,market_order_preference=%s,
                         margin_factor_pct=%s
                         ,current_bid=%s,current_ask=%s,size_increment_source=%s,
                         size_increment_authoritative=%s,raw_rule_sha256=%s
                       WHEN NOT MATCHED THEN INSERT
                         (broker_market_rule_id,broker_connection_id,market_id,min_deal_size,
                          size_increment,min_stop_distance,value_per_price_point_zar,
                          source_currency,observed_at_utc,stop_distance_unit,lot_size,market_status,
                          deal_currency,expiry,force_open_allowed,market_order_preference,margin_factor_pct,
                          current_bid,current_ask,size_increment_source,size_increment_authoritative,raw_rule_sha256)
                       VALUES(NEWID(),source.broker_connection_id,source.market_id,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
                    (
                        str(broker["broker_connection_id"]), str(market["market_id"]),
                        rule.min_deal_size, rule.size_increment, rule.min_stop_distance,
                        rule.value_per_price_unit_zar, rule.source_currency, rule.observed_at_utc,
                        rule.stop_distance_unit, rule.lot_size, rule.market_status,
                        rule.deal_currency, rule.expiry, rule.force_open_allowed, rule.market_order_preference,
                        rule.margin_factor_pct,
                        rule.current_bid, rule.current_ask,
                        rule.size_increment_source, rule.size_increment_authoritative, rule.raw_rule_sha256,
                        rule.min_deal_size, rule.size_increment, rule.min_stop_distance,
                        rule.value_per_price_unit_zar, rule.source_currency, rule.observed_at_utc,
                        rule.stop_distance_unit, rule.lot_size, rule.market_status,
                        rule.deal_currency, rule.expiry, rule.force_open_allowed, rule.market_order_preference,
                        rule.margin_factor_pct,
                        rule.current_bid, rule.current_ask,
                        rule.size_increment_source, rule.size_increment_authoritative, rule.raw_rule_sha256,
                    ),
                )
                outcomes.append({"symbol": market["symbol"], "result": "SYNCHRONIZED", "market_status": rule.market_status})
            connection.commit()
        return {"status": "completed", "markets": outcomes, "execution_enabled": False}
    finally:
        if owned_client:
            ig.close()


def _current_rule_symbols(settings: Settings) -> list[str]:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT m.symbol FROM app.markets m
               JOIN app.broker_market_rules r ON r.market_id=m.market_id
               JOIN app.broker_connections bc ON bc.broker_connection_id=r.broker_connection_id
               WHERE m.enabled=1 AND bc.environment='demo'
                 AND r.value_per_price_point_zar IS NOT NULL
                 AND r.observed_at_utc>=DATEADD(minute,-15,SYSUTCDATETIME())
               ORDER BY m.symbol"""
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _enabled_market_count(settings: Settings) -> int:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM app.markets WHERE enabled=1")
        return int(cursor.fetchone()[0])
