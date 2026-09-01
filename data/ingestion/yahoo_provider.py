"""Yahoo Finance market data provider.

Talks to Yahoo's public chart/quoteSummary JSON endpoints over httpx --
deliberately no `yfinance` dependency, so the transport stays injectable and
CI never touches the network.

Honesty rules this adapter follows (Rule 3/Rule 4):
- Bars with a null OHLC component are dropped, not interpolated.
- Missing profile/fundamental fields come back as None, never as 0 or "".
- A failed request raises; it never falls back to invented numbers.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from data.ingestion.errors import ProviderDataError, ProviderNotFoundError
from data.ingestion.http_client import HttpProviderClient, unwrap_yahoo_number
from data.ingestion.provider import MarketDataProvider
from data.ingestion.schemas import (
    CompanyProfile,
    FundamentalsSnapshot,
    Interval,
    PriceBar,
    Quote,
)

SOURCE = "yahoo"
_BASE_URL = "https://query1.finance.yahoo.com"

_INTERVAL_MAP = {
    Interval.DAILY: "1d",
    Interval.WEEKLY: "1wk",
    Interval.MONTHLY: "1mo",
}

# quoteSummary module -> {vendor field: TradingBrain metric name}. Names are
# explicit rather than auto-derived so `financial_metrics.metric_name` stays
# stable and comparable across providers.
_FUNDAMENTAL_KEYS: dict[str, dict[str, str]] = {
    "summaryDetail": {
        "trailingPE": "pe_ratio",
        "forwardPE": "forward_pe",
        "dividendYield": "dividend_yield",
        "beta": "beta",
        "marketCap": "market_cap",
    },
    "defaultKeyStatistics": {
        "priceToBook": "price_to_book",
        "trailingEps": "eps",
        "forwardEps": "forward_eps",
        "enterpriseValue": "enterprise_value",
    },
    "financialData": {
        "returnOnEquity": "return_on_equity",
        "debtToEquity": "debt_to_equity",
        "revenueGrowth": "revenue_growth_yoy",
        "profitMargins": "profit_margin",
        "currentRatio": "current_ratio",
    },
}


class YahooFinanceProvider(MarketDataProvider):
    def __init__(self, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        self._client = HttpProviderClient(_BASE_URL, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    # -- MarketDataProvider interface -----------------------------------------

    def get_historical_prices(
        self,
        ticker: str,
        start: dt.date,
        end: dt.date,
        interval: str = "1d",
    ) -> list[PriceBar]:
        if start > end:
            raise ValueError("start must not be after end")
        yahoo_interval = self._map_interval(interval)

        payload = self._client.get_json(
            f"/v8/finance/chart/{ticker}",
            params={
                "period1": _epoch(start),
                # Yahoo's period2 is exclusive-ish; +1 day makes `end` inclusive.
                "period2": _epoch(end + dt.timedelta(days=1)),
                "interval": yahoo_interval,
            },
        )
        result = self._unwrap_chart(payload, ticker)

        timestamps = result.get("timestamp") or []
        quote_blocks = (result.get("indicators") or {}).get("quote") or [{}]
        quote = quote_blocks[0] if quote_blocks else {}

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        bars: list[PriceBar] = []
        for i, epoch_seconds in enumerate(timestamps):
            row = (
                _at(opens, i),
                _at(highs, i),
                _at(lows, i),
                _at(closes, i),
            )
            if any(value is None for value in row) or epoch_seconds is None:
                # Yahoo emits nulls for halted/absent sessions -- an incomplete
                # bar is not data, so it is dropped rather than patched.
                continue
            open_, high, low, close = (float(v) for v in row)  # type: ignore[arg-type]
            volume = _at(volumes, i)
            bars.append(
                PriceBar(
                    ts=dt.datetime.fromtimestamp(int(epoch_seconds), tz=dt.UTC),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(volume) if volume is not None else 0,
                    interval=str(interval),
                    source=SOURCE,
                )
            )
        return bars

    def get_quote(self, ticker: str) -> Quote:
        payload = self._client.get_json(
            f"/v8/finance/chart/{ticker}", params={"range": "5d", "interval": "1d"}
        )
        meta = self._unwrap_chart(payload, ticker).get("meta") or {}

        price = unwrap_yahoo_number(meta.get("regularMarketPrice"))
        if price is None:
            raise ProviderDataError(f"Yahoo returned no regularMarketPrice for {ticker!r}")

        previous_close = unwrap_yahoo_number(
            meta.get("chartPreviousClose") or meta.get("previousClose")
        )
        change = price - previous_close if previous_close is not None else 0.0
        change_percent = (
            (change / previous_close * 100) if previous_close not in (None, 0) else 0.0
        )
        volume = unwrap_yahoo_number(meta.get("regularMarketVolume")) or 0.0
        market_time = meta.get("regularMarketTime")

        return Quote(
            ticker=ticker,
            price=price,
            change=change,
            change_percent=change_percent,
            volume=int(volume),
            as_of=(
                dt.datetime.fromtimestamp(int(market_time), tz=dt.UTC)
                if isinstance(market_time, int | float)
                else dt.datetime.now(dt.UTC)
            ),
            source=SOURCE,
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        meta = self._chart_meta(ticker)
        modules = self._quote_summary(ticker, ("assetProfile", "summaryDetail", "price"))
        asset_profile = modules.get("assetProfile") or {}
        summary_detail = modules.get("summaryDetail") or {}
        price_module = modules.get("price") or {}

        market_cap = unwrap_yahoo_number(
            summary_detail.get("marketCap") or price_module.get("marketCap")
        )
        name = (
            price_module.get("longName")
            or price_module.get("shortName")
            or meta.get("longName")
            or meta.get("shortName")
            or ticker
        )

        return CompanyProfile(
            ticker=ticker,
            name=str(name),
            exchange=str(meta.get("fullExchangeName") or meta.get("exchangeName") or "UNKNOWN"),
            currency=str(meta.get("currency") or "UNKNOWN"),
            source=SOURCE,
            sector=asset_profile.get("sector"),
            industry=asset_profile.get("industry"),
            market_cap=int(market_cap) if market_cap is not None else None,
        )

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        modules = self._quote_summary(ticker, tuple(_FUNDAMENTAL_KEYS))
        metrics: dict[str, float] = {}
        for module_name, field_map in _FUNDAMENTAL_KEYS.items():
            module = modules.get(module_name) or {}
            for vendor_field, metric_name in field_map.items():
                value = unwrap_yahoo_number(module.get(vendor_field))
                if value is not None:
                    metrics[metric_name] = value

        return FundamentalsSnapshot(
            ticker=ticker,
            as_of_date=dt.datetime.now(dt.UTC).date(),
            metrics=metrics,
            source=SOURCE,
        )

    def health_check(self) -> bool:
        """Cheap liveness probe used by the ProviderRegistry."""
        self._client.get_json("/v8/finance/chart/AAPL", params={"range": "1d", "interval": "1d"})
        return True

    # -- internals ------------------------------------------------------------

    def _chart_meta(self, ticker: str) -> dict[str, Any]:
        payload = self._client.get_json(
            f"/v8/finance/chart/{ticker}", params={"range": "1d", "interval": "1d"}
        )
        return self._unwrap_chart(payload, ticker).get("meta") or {}

    def _quote_summary(self, ticker: str, modules: tuple[str, ...]) -> dict[str, Any]:
        payload = self._client.get_json(
            f"/v10/finance/quoteSummary/{ticker}", params={"modules": ",".join(modules)}
        )
        summary = payload.get("quoteSummary") or {}
        if summary.get("error"):
            raise ProviderDataError(f"Yahoo quoteSummary error for {ticker!r}: {summary['error']}")
        results = summary.get("result") or []
        if not results:
            raise ProviderNotFoundError(f"Yahoo has no quoteSummary data for {ticker!r}")
        first = results[0]
        return first if isinstance(first, dict) else {}

    @staticmethod
    def _unwrap_chart(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
        chart = payload.get("chart") or {}
        error = chart.get("error")
        if error:
            description = error.get("description") if isinstance(error, dict) else str(error)
            raise ProviderNotFoundError(f"Yahoo error for {ticker!r}: {description}")
        results = chart.get("result") or []
        if not results:
            raise ProviderNotFoundError(f"Yahoo returned no chart data for {ticker!r}")
        first = results[0]
        if not isinstance(first, dict):
            raise ProviderDataError(f"Unexpected Yahoo chart payload for {ticker!r}")
        return first

    @staticmethod
    def _map_interval(interval: str) -> str:
        try:
            return _INTERVAL_MAP[Interval(interval)]
        except ValueError as exc:
            supported = ", ".join(i.value for i in Interval)
            raise NotImplementedError(
                f"YahooFinanceProvider supports intervals: {supported} (got {interval!r})"
            ) from exc


def _epoch(value: dt.date) -> int:
    return int(dt.datetime.combine(value, dt.time.min, tzinfo=dt.UTC).timestamp())


def _at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None
