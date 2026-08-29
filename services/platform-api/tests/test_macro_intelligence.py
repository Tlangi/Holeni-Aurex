from datetime import datetime, timezone

import pytest

from app.macro_intelligence import (
    OfficialSource,
    _classify,
    _html_item,
    _rss_items,
    _safe_source_url,
)


def test_official_source_allowlist_rejects_non_https_and_host_mismatch() -> None:
    with pytest.raises(ValueError):
        _safe_source_url("http://www.federalreserve.gov/feed.xml", "www.federalreserve.gov")
    with pytest.raises(ValueError):
        _safe_source_url("https://attacker.example/feed.xml", "www.federalreserve.gov")


def test_policy_and_inflation_classification_is_bounded() -> None:
    classification, score, impact = _classify(
        "CENTRAL_BANK", "Inflation remains elevated and upside risks to inflation require a rate increase",
    )
    assert classification == "HAWKISH"
    assert 0 < score <= 1
    assert impact == "HIGH"
    classification, score, _ = _classify("INFLATION", "Annual inflation fell and was down from last month")
    assert classification == "DISINFLATIONARY"
    assert -1 <= score < 0


def test_rss_parser_preserves_hashable_provenance_and_blocks_external_links() -> None:
    source = OfficialSource(
        "FED_POLICY", "Federal Reserve", "USD", "CENTRAL_BANK",
        "https://www.federalreserve.gov/feeds/press_monetary.xml", "RSS",
    )
    payload = b"""<rss><channel><item><title>Rate increase</title>
      <link>https://attacker.example/tracker</link><guid>release-1</guid>
      <pubDate>Wed, 12 Aug 2026 12:00:00 GMT</pubDate>
      <description>Inflation remains elevated.</description></item></channel></rss>"""
    items = _rss_items(payload, source, datetime(2026, 8, 25, tzinfo=timezone.utc))
    assert len(items) == 1
    assert items[0]["url"] == source.url
    assert len(str(items[0]["external_key"])) == 64
    assert items[0]["classification"] == "HAWKISH"


def test_calendar_html_extracts_upcoming_event_without_script_content() -> None:
    source = OfficialSource(
        "FED_CALENDAR", "Federal Reserve", "USD", "CALENDAR",
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "HTML",
    )
    payload = b"<html><head><title>Meeting calendar</title><script>September 1, 2026</script></head><body>Next meeting September 15-16, 2026</body></html>"
    item = _html_item(payload, source, datetime(2026, 8, 25, tzinfo=timezone.utc))[0]
    assert item["classification"] == "SCHEDULED_RISK"
    assert item["scheduled"].date().isoformat() == "2026-09-15"
