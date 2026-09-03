from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from app.config import Settings
from app.database import open_database
from app.model_pipeline import _market_frame, add_features
from app.shadow_engine import _artifact, _signal

logger = logging.getLogger("aurex.macro_intelligence")
PARSER_VERSION = "macro-v1"
SCORE_VERSION = "macro-score-v1"
DECISION_VERSION = "market-decision-v1"
MAX_RESPONSE_BYTES = 2_000_000
OFFICIAL_HOST_SUFFIXES = (
    "federalreserve.gov", "ecb.europa.eu", "bankofengland.co.uk", "boj.or.jp",
    "bls.gov", "ec.europa.eu", "ons.gov.uk", "stat.go.jp",
)


@dataclass(frozen=True)
class OfficialSource:
    code: str
    institution: str
    currency: str
    evidence_type: str
    url: str
    parser_kind: str
    priority: int = 5

    @property
    def host(self) -> str:
        return (urlparse(self.url).hostname or "").lower()


DEFAULT_SOURCES = (
    OfficialSource("FED_POLICY", "Federal Reserve", "USD", "CENTRAL_BANK", "https://www.federalreserve.gov/feeds/press_monetary.xml", "RSS", 10),
    OfficialSource("FED_CALENDAR", "Federal Reserve", "USD", "CALENDAR", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "HTML", 9),
    OfficialSource("US_CPI", "US Bureau of Labor Statistics", "USD", "INFLATION", "https://www.bls.gov/feed/cpi.rss", "RSS", 9),
    OfficialSource("ECB_POLICY", "European Central Bank", "EUR", "CENTRAL_BANK", "https://www.ecb.europa.eu/rss/press.html", "RSS", 10),
    OfficialSource("ECB_CALENDAR", "European Central Bank", "EUR", "CALENDAR", "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html", "HTML", 8),
    OfficialSource("EU_INFLATION", "Eurostat", "EUR", "INFLATION", "https://ec.europa.eu/eurostat/web/products-euro-indicators", "HTML", 8),
    OfficialSource("BOE_POLICY", "Bank of England", "GBP", "CENTRAL_BANK", "https://www.bankofengland.co.uk/news/latest-and-upcoming", "HTML", 10),
    OfficialSource("BOE_CALENDAR", "Bank of England", "GBP", "CALENDAR", "https://www.bankofengland.co.uk/news/upcoming", "HTML", 8),
    OfficialSource("UK_CPI", "Office for National Statistics", "GBP", "INFLATION", "https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/latest", "HTML", 9),
    OfficialSource("BOJ_POLICY", "Bank of Japan", "JPY", "CENTRAL_BANK", "https://www.boj.or.jp/en/whatsnew/index.htm", "HTML", 10),
    OfficialSource("BOJ_CALENDAR", "Bank of Japan", "JPY", "CALENDAR", "https://www.boj.or.jp/en/about/calendar/", "HTML", 9),
    OfficialSource("JP_CPI", "Statistics Bureau of Japan", "JPY", "INFLATION", "https://www.stat.go.jp/english/data/cpi/", "HTML", 9),
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._ignored = 0
        self._in_title = False

    def handle_starttag(self, tag: str, _: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)
            if self._in_title:
                self.title = f"{self.title} {value}".strip()


def _safe_source_url(url: str, expected_host: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != expected_host:
        raise ValueError("OFFICIAL_SOURCE_URL_MISMATCH")
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES):
        raise ValueError("UNAPPROVED_OFFICIAL_HOST")


def _read_response(response: requests.Response, expected_host: str) -> bytes:
    final_host = (urlparse(response.url).hostname or "").lower()
    if not any(final_host == suffix or final_host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES):
        raise ValueError("SOURCE_REDIRECTED_OFF_ALLOWLIST")
    content_type = response.headers.get("Content-Type", "").lower()
    if not any(kind in content_type for kind in ("xml", "html", "text")):
        raise ValueError("UNSUPPORTED_SOURCE_CONTENT_TYPE")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ValueError("OFFICIAL_SOURCE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _nearest_scheduled_date(text: str, now: datetime) -> datetime | None:
    months = {name.lower(): index for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1
    )}
    candidates: list[datetime] = []
    pattern = re.compile(r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:\s*[-–]\s*\d{1,2})?(?:,|\s)\s*(20\d{2})\b", re.I)
    for month, day, year in pattern.findall(text):
        try:
            value = datetime(int(year), months[month.lower()], int(day), 12, tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - timedelta(days=1) <= value <= now + timedelta(days=45):
            candidates.append(value)
    return min(candidates) if candidates else None


def _classify(evidence_type: str, text: str) -> tuple[str, float, str]:
    lowered = text.lower()
    if evidence_type == "CALENDAR":
        return "SCHEDULED_RISK", 0.0, "HIGH"
    hawkish = sum(lowered.count(term) for term in (
        "raise the", "rate increase", "increase bank rate", "tightening", "inflation remains elevated",
        "upside risks to inflation", "higher interest rate", "above target",
    ))
    dovish = sum(lowered.count(term) for term in (
        "rate cut", "lower the", "decrease bank rate", "easing", "disinflation", "below target",
        "weaker economic activity", "downside risks",
    ))
    if evidence_type == "INFLATION":
        rising = sum(lowered.count(term) for term in ("inflation up", "rose by", "increased", "up from"))
        falling = sum(lowered.count(term) for term in ("inflation down", "fell by", "decreased", "down from"))
        raw = max(-1.0, min(1.0, (rising - falling) / 4.0))
        return ("INFLATIONARY" if raw > 0.1 else "DISINFLATIONARY" if raw < -0.1 else "NEUTRAL", raw, "HIGH")
    raw = max(-1.0, min(1.0, (hawkish - dovish) / 4.0))
    return ("HAWKISH" if raw > 0.1 else "DOVISH" if raw < -0.1 else "NEUTRAL", raw, "HIGH")


def _rss_items(payload: bytes, source: OfficialSource, retrieved: datetime) -> list[dict[str, object]]:
    root = ET.fromstring(payload)
    items = root.findall(".//item")
    if not items:
        items = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "entry"]
    parsed: list[dict[str, object]] = []
    for item in items[:30]:
        fields: dict[str, str] = {}
        for child in item:
            key = child.tag.rsplit("}", 1)[-1]
            if key == "link" and child.attrib.get("href"):
                fields[key] = child.attrib["href"]
            elif child.text:
                fields[key] = child.text
        title = " ".join(html.unescape(fields.get("title", "Untitled official release")).split())[:500]
        link = fields.get("link") or source.url
        link_host = (urlparse(link).hostname or "").lower()
        if not any(link_host == suffix or link_host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES):
            link = source.url
        summary = " ".join(html.unescape(fields.get("description") or fields.get("summary") or title).split())
        published = _parse_date(fields.get("pubDate") or fields.get("published") or fields.get("updated"))
        classification, score, impact = _classify(source.evidence_type, f"{title} {summary}")
        external = fields.get("guid") or fields.get("id") or link or title
        parsed.append({"external_key": hashlib.sha256(external.encode()).hexdigest(), "title": title,
                       "url": link[:800], "published": published, "excerpt": summary[:2000],
                       "classification": classification, "score": score, "impact": impact,
                       "scheduled": _nearest_scheduled_date(f"{title} {summary}", retrieved) if source.evidence_type == "CALENDAR" else None})
    return parsed


def _html_item(payload: bytes, source: OfficialSource, retrieved: datetime) -> list[dict[str, object]]:
    decoder = payload.decode("utf-8", errors="replace")
    extractor = _VisibleText()
    extractor.feed(decoder)
    text = " ".join(extractor.parts)
    title = (extractor.title or source.institution)[:500]
    classification, score, impact = _classify(source.evidence_type, text[:50000])
    return [{"external_key": hashlib.sha256(source.url.encode()).hexdigest(), "title": title,
             "url": source.url, "published": None, "excerpt": text[:2000],
             "classification": classification, "score": score, "impact": impact,
             "scheduled": _nearest_scheduled_date(text[:50000], retrieved) if source.evidence_type == "CALENDAR" else None}]


def _ensure_sources(cursor: object) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for item in DEFAULT_SOURCES:
        _safe_source_url(item.url, item.host)
        cursor.execute("SELECT macro_source_id FROM app.macro_sources WHERE source_code=%s", (item.code,))
        existing = cursor.fetchone()
        source_id = str(existing["macro_source_id"]) if existing else str(uuid4())
        if existing:
            cursor.execute(
                """UPDATE app.macro_sources SET institution=%s,currency=%s,evidence_type=%s,source_url=%s,
                   official_host=%s,parser_kind=%s,priority=%s,updated_at_utc=SYSUTCDATETIME()
                   WHERE macro_source_id=%s""",
                (item.institution, item.currency, item.evidence_type, item.url, item.host,
                 item.parser_kind, item.priority, source_id),
            )
        else:
            cursor.execute(
                """INSERT app.macro_sources(macro_source_id,source_code,institution,currency,evidence_type,
                   source_url,official_host,parser_kind,priority,poll_seconds)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,900)""",
                (source_id, item.code, item.institution, item.currency, item.evidence_type,
                 item.url, item.host, item.parser_kind, item.priority),
            )
        identifiers[item.code] = source_id
    return identifiers


def _backfill_point_in_time_event_snapshots(cursor: object) -> int:
    """Preserve existing scheduled evidence as immutable retrieval-time vintages."""
    cursor.execute(
        """SELECT e.macro_evidence_id,s.source_code,e.external_key,s.currency,
                  e.scheduled_event_at_utc,e.impact,e.classification,e.title,e.canonical_url,
                  e.published_at_utc,e.retrieved_at_utc,e.content_sha256
           FROM app.macro_evidence e JOIN app.macro_sources s ON s.macro_source_id=e.macro_source_id
           WHERE e.scheduled_event_at_utc IS NOT NULL"""
    )
    inserted = 0
    for item in cursor.fetchall():
        payload = json.dumps({
            "title": item["title"], "canonical_url": item["canonical_url"],
            "scheduled_event_at_utc": item["scheduled_event_at_utc"].isoformat(),
            "published_at_utc": item["published_at_utc"].isoformat()
            if item.get("published_at_utc") else None,
            "retrieved_at_utc": item["retrieved_at_utc"].isoformat(),
            "impact": item["impact"], "classification": item["classification"],
            "source_content_sha256": item["content_sha256"], "backfilled": True,
        }, sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        cursor.execute(
            """IF NOT EXISTS(SELECT 1 FROM app.economic_event_snapshots
               WHERE source_code=%s AND external_key=%s AND retrieved_at_utc=%s AND payload_sha256=%s)
               INSERT app.economic_event_snapshots
                 (economic_event_snapshot_id,macro_evidence_id,source_code,external_key,currency,
                  event_at_utc,impact,classification,title,retrieved_at_utc,available_from_utc,
                  payload_sha256,payload_json)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (item["source_code"], item["external_key"], item["retrieved_at_utc"], digest,
             str(uuid4()), str(item["macro_evidence_id"]), item["source_code"], item["external_key"],
             item["currency"], item["scheduled_event_at_utc"], item["impact"],
             item["classification"], item["title"], item["retrieved_at_utc"],
             item["retrieved_at_utc"], digest, payload),
        )
        inserted += max(0, int(cursor.rowcount or 0))
    return inserted


def sync_official_macro_sources(settings: Settings, *, session: requests.Session | None = None) -> dict[str, object]:
    if not settings.macro_intelligence_enabled:
        return {"status": "disabled", "sources": [], "evidence_inserted": 0}
    owned = session is None
    http = session or requests.Session()
    inserted = 0
    outcomes: list[dict[str, object]] = []
    now = datetime.now(timezone.utc)
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            source_ids = _ensure_sources(cursor)
            snapshot_backfill = _backfill_point_in_time_event_snapshots(cursor)
            connection.commit()
            for source in DEFAULT_SOURCES:
                source_id = source_ids[source.code]
                _safe_source_url(source.url, source.host)
                try:
                    response = http.get(source.url, headers={
                                        "User-Agent": "Mozilla/5.0 (compatible; AurexMacroIntelligence/1.0; official-source-monitor)",
                                        "Accept": "application/rss+xml, application/xml, text/html;q=0.9, text/plain;q=0.8",
                                        "Accept-Language": "en-ZA,en;q=0.8",
                                    },
                                        timeout=settings.macro_source_timeout_seconds, stream=True)
                    response.raise_for_status()
                    payload = _read_response(response, source.host)
                    items = _rss_items(payload, source, now) if source.parser_kind == "RSS" else _html_item(payload, source, now)
                    for item in items:
                        content_hash = hashlib.sha256(str(item["excerpt"]).encode()).hexdigest()
                        evidence_id = str(uuid4())
                        cursor.execute(
                            """IF NOT EXISTS(SELECT 1 FROM app.macro_evidence WHERE macro_source_id=%s AND external_key=%s AND content_sha256=%s)
                               INSERT app.macro_evidence(macro_evidence_id,macro_source_id,external_key,title,canonical_url,
                                 published_at_utc,retrieved_at_utc,content_sha256,content_excerpt,classification,currency_score,
                                 impact,scheduled_event_at_utc,parser_version,metadata_json)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (source_id, item["external_key"], content_hash, evidence_id, source_id,
                             item["external_key"], item["title"], item["url"], item["published"], now,
                             content_hash, item["excerpt"], item["classification"], item["score"], item["impact"],
                             item["scheduled"], PARSER_VERSION, json.dumps({"source_code": source.code})),
                        )
                        inserted += max(0, int(cursor.rowcount or 0))
                        cursor.execute(
                            """SELECT TOP (1) macro_evidence_id FROM app.macro_evidence
                               WHERE macro_source_id=%s AND external_key=%s AND content_sha256=%s
                               ORDER BY retrieved_at_utc DESC""",
                            (source_id, item["external_key"], content_hash),
                        )
                        stored_evidence = cursor.fetchone()
                        if item.get("scheduled") and stored_evidence:
                            snapshot = {
                                "title": item["title"], "canonical_url": item["url"],
                                "scheduled_event_at_utc": item["scheduled"].isoformat(),
                                "published_at_utc": item["published"].isoformat()
                                if item.get("published") else None,
                                "retrieved_at_utc": now.isoformat(), "impact": item["impact"],
                                "classification": item["classification"],
                                "currency_score": item["score"], "parser_version": PARSER_VERSION,
                            }
                            snapshot_json = json.dumps(snapshot, sort_keys=True)
                            snapshot_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()
                            cursor.execute(
                                """IF NOT EXISTS(SELECT 1 FROM app.economic_event_snapshots
                                   WHERE source_code=%s AND external_key=%s AND retrieved_at_utc=%s
                                     AND payload_sha256=%s)
                                   INSERT app.economic_event_snapshots
                                     (economic_event_snapshot_id,macro_evidence_id,source_code,external_key,
                                      currency,event_at_utc,impact,classification,title,retrieved_at_utc,
                                      available_from_utc,payload_sha256,payload_json)
                                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (source.code, item["external_key"], now, snapshot_hash, str(uuid4()),
                                 str(stored_evidence["macro_evidence_id"]), source.code,
                                 item["external_key"], source.currency, item["scheduled"],
                                 item["impact"], item["classification"], item["title"], now, now,
                                 snapshot_hash, snapshot_json),
                            )
                    cursor.execute(
                        """UPDATE app.macro_sources SET last_attempt_at_utc=%s,last_success_at_utc=%s,
                           last_http_status=%s,last_error_code=NULL,etag=%s,last_modified=%s,updated_at_utc=SYSUTCDATETIME()
                           WHERE macro_source_id=%s""",
                        (now, now, response.status_code, response.headers.get("ETag"),
                         response.headers.get("Last-Modified"), source_id),
                    )
                    connection.commit()
                    outcomes.append({"source": source.code, "status": "CURRENT", "items": len(items)})
                except Exception as exc:
                    connection.rollback()
                    error_code = type(exc).__name__.upper()[:80]
                    cursor.execute(
                        """UPDATE app.macro_sources SET last_attempt_at_utc=%s,last_error_code=%s,
                           updated_at_utc=SYSUTCDATETIME() WHERE macro_source_id=%s""",
                        (now, error_code, source_id),
                    )
                    connection.commit()
                    outcomes.append({"source": source.code, "status": "ERROR", "error_code": error_code})
                    logger.warning("official macro source failed", extra={"worker": "macro_intelligence",
                                   "operation": f"macro.fetch.{source.code}", "result": error_code})
            scores = calculate_currency_scores(settings, cursor=cursor, now=now)
            successful = sum(1 for item in outcomes if item["status"] == "CURRENT")
            component_status = "CURRENT" if successful >= 8 else "DEGRADED" if successful else "ERROR"
            cursor.execute(
                """UPDATE app.platform_components SET status=%s,status_detail=%s,checked_at_utc=SYSUTCDATETIME()
                   WHERE component_code='macro_intelligence'""",
                (component_status, f"Official sources current: {successful}/{len(outcomes)}; evidence inserted: {inserted}"[:300]),
            )
            connection.commit()
        return {"status": component_status, "sources": outcomes, "evidence_inserted": inserted,
                "event_snapshots_backfilled": snapshot_backfill, "scores": scores}
    finally:
        if owned:
            http.close()


def calculate_currency_scores(settings: Settings, *, cursor: object, now: datetime) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    cutoff = now - timedelta(hours=settings.macro_evidence_max_age_hours)
    for currency in ("USD", "EUR", "GBP", "JPY"):
        cursor.execute(
            """SELECT TOP (30) e.macro_evidence_id,e.title,e.canonical_url,e.classification,
                      e.currency_score,e.impact,e.published_at_utc,e.retrieved_at_utc,e.scheduled_event_at_utc,
                      s.evidence_type,s.priority
               FROM app.macro_evidence e JOIN app.macro_sources s ON s.macro_source_id=e.macro_source_id
               WHERE s.currency=%s AND e.retrieved_at_utc>=%s
               ORDER BY COALESCE(e.published_at_utc,e.retrieved_at_utc) DESC""",
            (currency, cutoff),
        )
        evidence = cursor.fetchall()
        policy_values: list[tuple[float, float]] = []
        inflation_values: list[tuple[float, float]] = []
        event_risk = 0.0
        references: list[dict[str, object]] = []
        for item in evidence:
            observed = item["published_at_utc"] or item["retrieved_at_utc"]
            age_days = max(0.0, (now - observed.replace(tzinfo=timezone.utc)).total_seconds() / 86400)
            weight = float(item["priority"]) / 10 * math.exp(-age_days / 14)
            if item["evidence_type"] == "CENTRAL_BANK":
                policy_values.append((float(item["currency_score"]), weight))
            elif item["evidence_type"] == "INFLATION":
                inflation_values.append((float(item["currency_score"]), weight))
            scheduled = item["scheduled_event_at_utc"]
            if scheduled:
                distance = abs((scheduled.replace(tzinfo=timezone.utc) - now).total_seconds()) / 60
                if distance <= settings.macro_event_blackout_minutes:
                    event_risk = 1.0
                elif distance <= 24 * 60:
                    event_risk = max(event_risk, 0.6)
            references.append({"id": str(item["macro_evidence_id"]), "title": item["title"],
                               "url": item["canonical_url"], "classification": item["classification"]})
        weighted = lambda values: sum(value * weight for value, weight in values) / sum(weight for _, weight in values) if values else 0.0
        policy, inflation = weighted(policy_values), weighted(inflation_values)
        composite = max(-1.0, min(1.0, policy * 0.7 + inflation * 0.3))
        coverage = {str(item["evidence_type"]) for item in evidence}
        complete_coverage = {"CENTRAL_BANK", "INFLATION", "CALENDAR"}.issubset(coverage)
        valid_until = now + timedelta(seconds=settings.macro_sync_seconds * 2) if complete_coverage else now - timedelta(seconds=1)
        score_id = str(uuid4())
        cursor.execute(
            """INSERT app.macro_currency_scores(macro_currency_score_id,currency,as_of_utc,policy_score,
               inflation_score,event_risk_score,composite_score,evidence_count,valid_until_utc,evidence_json,score_version)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (score_id, currency, now, policy, inflation, event_risk, composite, len(evidence),
             valid_until, json.dumps(references[:12], default=str), SCORE_VERSION),
        )
        results.append({"currency": currency, "policy_score": round(policy, 4),
                        "inflation_score": round(inflation, 4), "event_risk": event_risk,
                        "composite_score": round(composite, 4), "evidence_count": len(evidence),
                        "coverage": sorted(coverage), "coverage_complete": complete_coverage})
    return results


def _latest_currency_scores(cursor: object, now: datetime) -> dict[str, dict[str, object]]:
    cursor.execute(
        """SELECT currency,composite_score,event_risk_score,as_of_utc,valid_until_utc,evidence_json
           FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY currency ORDER BY as_of_utc DESC) rn
                 FROM app.macro_currency_scores) ranked WHERE rn=1 AND evidence_count>0"""
    )
    return {str(row["currency"]): dict(row) for row in cursor.fetchall() if row["valid_until_utc"].replace(tzinfo=timezone.utc) >= now}


def generate_market_decisions(settings: Settings, tenant_id: str) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        macro = _latest_currency_scores(cursor, now)
        cursor.execute(
            """SELECT market_id,symbol,base_currency,quote_currency,market_tier,
                      signal_enabled,demo_trading_enabled
               FROM app.markets WHERE enabled=1 AND research_enabled=1
               ORDER BY market_tier,symbol"""
        )
        markets = cursor.fetchall()
        for market in markets:
            frame = _market_frame(connection.cursor(), str(market["market_id"]))
            featured = add_features(frame, labelled=False) if not frame.empty else pd.DataFrame()
            if featured.empty:
                outcomes.append({"symbol": market["symbol"], "decision": "HOLD", "blocker": "INSUFFICIENT_FEATURES"})
                continue
            latest = featured.iloc[-1]
            atr_pct = max(float(latest["atr_pct"]), 1e-9)
            trend = math.tanh(float(latest["ema_gap"]) / atr_pct * 1.5)
            momentum = math.tanh(float(latest["ret4"]) / atr_pct)
            rsi = max(-1.0, min(1.0, (float(latest["rsi"]) - 50) / 50))
            technical = max(-1.0, min(1.0, trend * 0.45 + momentum * 0.35 + rsi * 0.20))
            base = macro.get(str(market["base_currency"]))
            quote = macro.get(str(market["quote_currency"]))
            macro_current = base is not None and quote is not None
            macro_score = ((float(base["composite_score"]) - float(quote["composite_score"])) / 2) if macro_current else 0.0
            event_risk = max(float(base["event_risk_score"]), float(quote["event_risk_score"])) if macro_current else 1.0
            cursor.execute(
                """SELECT TOP (1) mv.model_version_id,mv.artifact_path,mv.artifact_sha256,
                          sv.buy_threshold,sv.sell_threshold
                   FROM app.model_versions mv JOIN app.strategy_versions sv ON sv.strategy_version_id=mv.strategy_version_id
                   WHERE mv.market_id=%s AND mv.status='VALIDATED' ORDER BY mv.registered_at_utc DESC""",
                (str(market["market_id"]),),
            )
            model = cursor.fetchone()
            model_score: float | None = None
            model_direction = "UNAVAILABLE"
            if model:
                try:
                    bundle = _artifact(str(model["artifact_path"]), str(model["artifact_sha256"]))
                    model_direction, confidence, _ = _signal(frame, bundle, float(model["buy_threshold"]), float(model["sell_threshold"]))
                    model_score = float(confidence) if model_direction == "BUY" else -float(confidence) if model_direction == "SELL" else 0.0
                except Exception:
                    model = None
                    model_direction = "INVALID_ARTIFACT"
            combined = technical * 0.65 + macro_score * 0.35 if model_score is None else technical * 0.35 + macro_score * 0.20 + model_score * 0.45
            combined = max(-1.0, min(1.0, combined))
            blocker: str | None = None
            if not macro_current:
                decision, blocker = "HOLD", "MACRO_EVIDENCE_STALE"
            elif event_risk >= 0.75:
                decision, blocker = "HOLD", "HIGH_IMPACT_EVENT_WINDOW"
            elif abs(combined) < settings.macro_decision_threshold:
                decision, blocker = "HOLD", "NO_COMBINED_EDGE"
            else:
                decision = "BUY" if combined > 0 else "SELL"
                if model_score is None:
                    blocker = "MODEL_NOT_VALIDATED"
                elif model_direction == "HOLD":
                    blocker = "MODEL_NO_TRADE_SIGNAL"
                elif model_direction != decision:
                    blocker = "MODEL_MACRO_DIRECTION_CONFLICT"
            executable = decision != "HOLD" and blocker is None
            if int(market["market_tier"]) == 3:
                decision, executable, blocker = "HOLD", False, "RESEARCH_ONLY"
            elif not bool(market["signal_enabled"]) or not bool(market["demo_trading_enabled"]):
                decision, executable, blocker = "HOLD", False, "MARKET_NOT_PROMOTED"
            cursor.execute(
                "SELECT TOP (1) candle_id FROM app.candles WHERE market_id=%s AND timeframe='M15' AND completed=1 AND quality_status='PASS' AND is_regular_session=1 ORDER BY open_time_utc DESC",
                (str(market["market_id"]),),
            )
            candle_id = int(cursor.fetchone()["candle_id"])
            evidence = {"technical": {"trend": trend, "momentum": momentum, "rsi": rsi},
                        "macro": {"base": str(market["base_currency"]), "quote": str(market["quote_currency"]),
                                  "base_score": float(base["composite_score"]) if base else None,
                                  "quote_score": float(quote["composite_score"]) if quote else None},
                        "model": {"status": "VALIDATED" if model else "NOT_VALIDATED", "direction": model_direction},
                        "market_eligibility": {
                            "tier": int(market["market_tier"]),
                            "signal_enabled": bool(market["signal_enabled"]),
                            "demo_trading_enabled": bool(market["demo_trading_enabled"]),
                        },
                        "risk_authority": "DETERMINISTIC_RISK_ENGINE"}
            input_payload = json.dumps({"tenant": tenant_id, "market": str(market["market_id"]), "candle": candle_id,
                                        "technical": round(technical, 8), "macro": round(macro_score, 8),
                                        "model": model_score, "event": event_risk}, sort_keys=True)
            digest = hashlib.sha256(input_payload.encode()).hexdigest()
            cursor.execute(
                """IF NOT EXISTS(SELECT 1 FROM app.market_decisions WHERE tenant_id=%s AND market_id=%s AND input_sha256=%s)
                   INSERT app.market_decisions(market_decision_id,tenant_id,market_id,candle_id,model_version_id,decision,
                     technical_score,model_score,macro_score,event_risk_score,combined_score,confidence,executable,
                     blocker_code,evidence_json,input_sha256,decision_version,generated_at_utc)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (tenant_id, str(market["market_id"]), digest, str(uuid4()), tenant_id, str(market["market_id"]),
                 candle_id, str(model["model_version_id"]) if model else None, decision, technical, model_score,
                 macro_score, event_risk, combined, abs(combined), executable, blocker,
                 json.dumps(evidence, default=str), digest, DECISION_VERSION, now),
            )
            outcomes.append({"symbol": market["symbol"], "decision": decision, "technical_score": round(technical, 4),
                             "macro_score": round(macro_score, 4), "model_score": round(model_score, 4) if model_score is not None else None,
                             "combined_score": round(combined, 4), "confidence": round(abs(combined), 4),
                             "executable": executable, "blocker": blocker})
        connection.commit()
    return outcomes


def read_macro_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT source_code,institution,currency,evidence_type,source_url,enabled,last_attempt_at_utc,
                      last_success_at_utc,last_http_status,last_error_code
               FROM app.macro_sources ORDER BY currency,evidence_type,source_code"""
        )
        sources = cursor.fetchall()
        cursor.execute(
            """SELECT currency,as_of_utc,policy_score,inflation_score,event_risk_score,composite_score,
                      evidence_count,valid_until_utc,evidence_json
               FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY currency ORDER BY as_of_utc DESC) rn
                     FROM app.macro_currency_scores) ranked WHERE rn=1 ORDER BY currency"""
        )
        scores = cursor.fetchall()
        cursor.execute(
            """SELECT symbol,decision,technical_score,model_score,macro_score,event_risk_score,
                      combined_score,confidence,executable,blocker_code,evidence_json,generated_at_utc
               FROM (SELECT m.symbol,d.*,ROW_NUMBER() OVER(PARTITION BY d.market_id ORDER BY d.generated_at_utc DESC) rn
                     FROM app.market_decisions d JOIN app.markets m ON m.market_id=d.market_id
                     WHERE d.tenant_id=%s) ranked WHERE rn=1 ORDER BY symbol""", (tenant_id,),
        )
        decisions = cursor.fetchall()
        cursor.execute(
            """SELECT TOP (50) source_code,external_key,currency,event_at_utc,impact,
                      classification,title,retrieved_at_utc,available_from_utc,payload_sha256
               FROM app.economic_event_snapshots
               ORDER BY event_at_utc DESC,retrieved_at_utc DESC"""
        )
        event_snapshots = cursor.fetchall()
    def iso(value: object) -> str | None:
        return value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value, datetime) else None
    return {
        "status": "CURRENT" if len(scores) == 4 and all(int(row["evidence_count"]) > 0 and row["valid_until_utc"].replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc) for row in scores) else "STALE",
        "sources": [{**{key: value for key, value in row.items() if not isinstance(value, datetime)},
                     "last_attempt_at_utc": iso(row["last_attempt_at_utc"]), "last_success_at_utc": iso(row["last_success_at_utc"])} for row in sources],
        "currencies": [{"currency": row["currency"], "as_of_utc": iso(row["as_of_utc"]),
                        "policy_score": str(row["policy_score"]), "inflation_score": str(row["inflation_score"]),
                        "event_risk_score": str(row["event_risk_score"]), "composite_score": str(row["composite_score"]),
                        "evidence_count": int(row["evidence_count"]), "valid_until_utc": iso(row["valid_until_utc"]),
                        "evidence": json.loads(row["evidence_json"])} for row in scores],
        "decisions": [{"symbol": row["symbol"], "decision": row["decision"],
                       "technical_score": str(row["technical_score"]),
                       "model_score": str(row["model_score"]) if row["model_score"] is not None else None,
                       "macro_score": str(row["macro_score"]), "event_risk_score": str(row["event_risk_score"]),
                       "combined_score": str(row["combined_score"]), "confidence": str(row["confidence"]),
                       "executable": bool(row["executable"]), "blocker": row["blocker_code"],
                       "evidence": json.loads(row["evidence_json"]), "generated_at_utc": iso(row["generated_at_utc"])} for row in decisions],
        "event_snapshots": [{"source_code": row["source_code"], "external_key": row["external_key"],
                             "currency": row["currency"], "event_at_utc": iso(row["event_at_utc"]),
                             "impact": row["impact"], "classification": row["classification"],
                             "title": row["title"], "retrieved_at_utc": iso(row["retrieved_at_utc"]),
                             "available_from_utc": iso(row["available_from_utc"]),
                             "payload_sha256": row["payload_sha256"]} for row in event_snapshots],
        "event_regime_enabled": False,
        "event_regime_blocker": "REQUIRES_SUFFICIENT_POINT_IN_TIME_SNAPSHOT_HISTORY",
        "execution_authority": "DETERMINISTIC_RISK_ENGINE",
    }
