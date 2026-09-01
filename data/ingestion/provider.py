"""Market data provider abstraction.

TradingBrain must never be hard-coded around a single data vendor. All
callers depend on `MarketDataProvider`; `MockProvider` is the only
implementation in this phase, and requires no external API key. Real
providers (e.g. a broker/exchange data feed) plug in later without touching
callers.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from data.ingestion.schemas import CompanyProfile, FundamentalsSnapshot, PriceBar, Quote


class MarketDataProvider(ABC):
    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Latest price snapshot for a ticker."""

    @abstractmethod
    def get_historical_prices(
        self,
        ticker: str,
        start: dt.date,
        end: dt.date,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """OHLCV bars for `ticker` between `start` and `end`, inclusive."""

    @abstractmethod
    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Static/slow-changing company metadata."""

    @abstractmethod
    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        """Latest available fundamental metrics for `ticker`."""
