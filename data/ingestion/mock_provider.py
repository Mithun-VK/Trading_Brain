"""Deterministic synthetic market data provider. Requires no external API
key, so local development and CI never depend on a real vendor. Every
returned object is tagged `source="mock"` — never treat this as real market
data (Rule 4).

Determinism: each ticker gets its own seeded random walk anchored at a fixed
epoch, so repeated calls (even across processes) return identical bars for
the same ticker/date range.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random

from data.ingestion.provider import MarketDataProvider
from data.ingestion.schemas import CompanyProfile, FundamentalsSnapshot, PriceBar, Quote

_EPOCH = dt.date(2000, 1, 1)
_SECTORS = (
    "Technology",
    "Financials",
    "Energy",
    "Healthcare",
    "Consumer Discretionary",
    "Industrials",
)


def _seed_for(ticker: str, salt: int = 0) -> int:
    digest = hashlib.sha256(f"{ticker.upper()}:{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class MockProvider(MarketDataProvider):
    def _walk(self, ticker: str, end: dt.date) -> list[PriceBar]:
        rng = random.Random(_seed_for(ticker))
        price = 50 + rng.random() * 950
        bars: list[PriceBar] = []
        current = _EPOCH
        while current <= end:
            if current.weekday() < 5:
                daily_return = rng.gauss(0.0003, 0.02)
                open_price = price
                close_price = max(0.01, price * (1 + daily_return))
                high_price = max(open_price, close_price) * (1 + abs(rng.gauss(0, 0.005)))
                low_price = min(open_price, close_price) * (1 - abs(rng.gauss(0, 0.005)))
                volume = int(rng.uniform(1e5, 5e6))
                bars.append(
                    PriceBar(
                        ts=dt.datetime.combine(current, dt.time(16, 0), tzinfo=dt.UTC),
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        interval="1d",
                        source="mock",
                    )
                )
                price = close_price
            current += dt.timedelta(days=1)
        return bars

    def get_historical_prices(
        self,
        ticker: str,
        start: dt.date,
        end: dt.date,
        interval: str = "1d",
    ) -> list[PriceBar]:
        if interval != "1d":
            raise NotImplementedError("MockProvider currently only supports interval='1d'")
        if start > end:
            raise ValueError("start must not be after end")
        return [bar for bar in self._walk(ticker, end) if bar.ts.date() >= start]

    def get_quote(self, ticker: str) -> Quote:
        today = dt.datetime.now(dt.UTC).date()
        bars = self.get_historical_prices(ticker, today - dt.timedelta(days=10), today)
        if not bars:
            raise ValueError(f"No mock price data available for {ticker!r}")
        last = bars[-1]
        prev = bars[-2] if len(bars) > 1 else last
        change = last.close - prev.close
        change_percent = (change / prev.close * 100) if prev.close else 0.0
        return Quote(
            ticker=ticker,
            price=last.close,
            change=change,
            change_percent=change_percent,
            volume=last.volume,
            as_of=last.ts,
            source="mock",
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        rng = random.Random(_seed_for(ticker, salt=1))
        sector = _SECTORS[rng.randrange(len(_SECTORS))]
        return CompanyProfile(
            ticker=ticker,
            name=f"{ticker.upper()} Mock Corp",
            exchange="MOCK",
            sector=sector,
            industry=f"{sector} Services",
            market_cap=int(rng.uniform(1e8, 5e11)),
            currency="USD",
            source="mock",
        )

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        rng = random.Random(_seed_for(ticker, salt=2))
        metrics = {
            "pe_ratio": round(rng.uniform(5, 60), 2),
            "eps": round(rng.uniform(-5, 50), 2),
            "revenue_growth_yoy": round(rng.uniform(-0.2, 0.5), 4),
            "debt_to_equity": round(rng.uniform(0, 3), 2),
            "roe": round(rng.uniform(-0.1, 0.4), 4),
        }
        return FundamentalsSnapshot(
            ticker=ticker,
            as_of_date=dt.datetime.now(dt.UTC).date(),
            metrics=metrics,
            source="mock",
        )
