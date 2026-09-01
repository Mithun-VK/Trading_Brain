"""DTOs returned by a `MarketDataProvider`. These are provider-facing shapes,
distinct from the `models/` ORM rows they eventually get normalized into
(`data/normalization/`) — a provider should never need to know about the
database schema.

Every DTO carries `source` so mock/demo data is always distinguishable from
real data (Rule 4: never fabricate live financial data and present it as
real).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum


class Interval(StrEnum):
    """Bar intervals TradingBrain persists. Values double as the string
    stored in `prices.interval`, so comparisons against plain "1d" still work.
    """

    DAILY = "1d"
    WEEKLY = "1wk"
    MONTHLY = "1mo"


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    change: float
    change_percent: float
    volume: int
    as_of: dt.datetime
    source: str


@dataclass(frozen=True)
class PriceBar:
    ts: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    interval: str
    source: str


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    exchange: str
    currency: str
    source: str
    # Optional because real vendors genuinely don't always expose these --
    # a missing sector is reported as None, never invented (Rule 4).
    sector: str | None = None
    industry: str | None = None
    market_cap: int | None = None


@dataclass(frozen=True)
class FundamentalsSnapshot:
    ticker: str
    as_of_date: dt.date
    metrics: dict[str, float] = field(default_factory=dict)
    source: str = "unknown"
