from __future__ import annotations

"""Vendor-neutral historical M1 normalization; downloading is handled by bounded workers."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Protocol


class PriceCompleteness(StrEnum):
    BID_ASK_FULL = "BID_ASK_FULL"
    BID_ONLY = "BID_ONLY"
    MID_ONLY = "MID_ONLY"


class InstrumentEquivalence(StrEnum):
    EXACT_PAIR = "EXACT_PAIR"
    CLOSE_PROXY = "CLOSE_PROXY"
    INDEX_REFERENCE = "INDEX_REFERENCE"
    BROKER_SPECIFIC = "BROKER_SPECIFIC"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class NormalizedM1:
    timestamp_utc: datetime
    bid_open: Decimal | None; bid_high: Decimal | None; bid_low: Decimal | None; bid_close: Decimal | None
    ask_open: Decimal | None; ask_high: Decimal | None; ask_low: Decimal | None; ask_close: Decimal | None
    tick_count: int
    completeness: PriceCompleteness

    def __post_init__(self) -> None:
        if self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() != timedelta(0):
            raise ValueError("canonical M1 timestamps must be UTC-aware")
        for side in ((self.bid_open,self.bid_high,self.bid_low,self.bid_close),
                     (self.ask_open,self.ask_high,self.ask_low,self.ask_close)):
            values = [value for value in side if value is not None]
            if values and (len(values) != 4 or min(values) <= 0 or values[1] < max(values[0],values[3]) or values[2] > min(values[0],values[3])):
                raise ValueError("invalid side-specific OHLC")
        if self.completeness != PriceCompleteness.BID_ASK_FULL and any(
                value is not None for value in (self.ask_open,self.ask_high,self.ask_low,self.ask_close)):
            raise ValueError("ask evidence cannot exist on a non-bid/ask row")


class HistoricalMarketDataProvider(Protocol):
    vendor: str
    def parse_partition(self, lines: Iterable[str]) -> Iterable[NormalizedM1]: ...


FIXED_EST = timezone(timedelta(hours=-5), name="EST_NO_DST")


def parse_histdata_m1(line: str) -> NormalizedM1:
    """Parse documented Generic ASCII M1: fixed EST and BID OHLC only."""
    fields = line.strip().split(";")
    if len(fields) != 6:
        raise ValueError("invalid HistData M1 field count")
    opened = datetime.strptime(fields[0], "%Y%m%d %H%M%S").replace(tzinfo=FIXED_EST).astimezone(timezone.utc)
    bid = tuple(Decimal(value) for value in fields[1:5])
    return NormalizedM1(opened, *bid, None,None,None,None, int(fields[5] or 0), PriceCompleteness.BID_ONLY)


@dataclass(frozen=True)
class Tick:
    timestamp_utc: datetime
    bid: Decimal
    ask: Decimal


def parse_histdata_tick(line: str) -> Tick:
    fields = line.strip().split(",")
    if len(fields) != 4:
        raise ValueError("invalid HistData tick field count")
    opened = datetime.strptime(fields[0], "%Y%m%d %H%M%S%f").replace(tzinfo=FIXED_EST).astimezone(timezone.utc)
    bid, ask = Decimal(fields[1]), Decimal(fields[2])
    if bid <= 0 or ask < bid:
        raise ValueError("invalid bid/ask tick")
    return Tick(opened, bid, ask)


def aggregate_ticks_to_m1(ticks: Iterable[Tick]) -> list[NormalizedM1]:
    buckets: dict[datetime,list[Tick]] = {}
    for tick in ticks:
        bucket = tick.timestamp_utc.replace(second=0,microsecond=0)
        buckets.setdefault(bucket,[]).append(tick)
    result: list[NormalizedM1] = []
    for opened, rows in sorted(buckets.items()):
        bids, asks = [row.bid for row in rows], [row.ask for row in rows]
        result.append(NormalizedM1(opened,bids[0],max(bids),min(bids),bids[-1],
                                   asks[0],max(asks),min(asks),asks[-1],len(rows),
                                   PriceCompleteness.BID_ASK_FULL))
    return result


SOURCE_PRIORITY = (
    "DUKASCOPY_TICK_BID_ASK", "DUKASCOPY_BAR", "HISTDATA_TICK_BID_ASK",
    "HISTDATA_M1_BID", "OTHER_VERIFIED",
)


def research_eligible(*, quality_state: str, equivalence: InstrumentEquivalence,
                      point_in_time_verified: bool) -> bool:
    return quality_state in {"VALIDATED", "GOOD"} and point_in_time_verified and equivalence in {
        InstrumentEquivalence.EXACT_PAIR, InstrumentEquivalence.BROKER_SPECIFIC,
    }
