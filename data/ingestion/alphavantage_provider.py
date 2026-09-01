"""Alpha Vantage market data provider.

Alpha Vantage signals rate limiting in the *body* (a "Note"/"Information"
key) with HTTP 200, so that case is translated explicitly -- otherwise a
throttled response would look like an empty-but-successful result and the
registry would never fail over.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from data.ingestion.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from data.ingestion.http_client import HttpProviderClient
from data.ingestion.provider import MarketDataProvider
from data.ingestion.schemas import (
    CompanyProfile,
    FundamentalsSnapshot,
    Interval,
    PriceBar,
    Quote,
)

SOURCE = "alphavantage"
_BASE_URL = "https://www.alphavantage.co"

_SERIES_FUNCTIONS = {
    Interval.DAILY: ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    Interval.WEEKLY: ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    Interval.MONTHLY: ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}

_OVERVIEW_METRICS = {
    "PERatio": "pe_ratio",
    "ForwardPE": "forward_pe",
    "EPS": "eps",
    "PriceToBookRatio": "price_to_book",
    "ReturnOnEquityTTM": "return_on_equity",
    "ProfitMargin": "profit_margin",
    "QuarterlyRevenueGrowthYOY": "revenue_growth_yoy",
    "DividendYield": "dividend_yield",
    "Beta": "beta",
}


class AlphaVantageProvider(MarketDataProvider):
    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderAuthError("ALPHAVANTAGE_API_KEY is not configured")
        self._api_key = api_key
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
        try:
            function, series_key = _SERIES_FUNCTIONS[Interval(interval)]
        except ValueError as exc:
            supported = ", ".join(i.value for i in Interval)
            raise NotImplementedError(
                f"AlphaVantageProvider supports intervals: {supported} (got {interval!r})"
            ) from exc

        payload = self._query({"function": function, "symbol": ticker, "outputsize": "full"})
        series = payload.get(series_key)
        if not isinstance(series, dict):
            raise ProviderNotFoundError(f"Alpha Vantage returned no {series_key} for {ticker!r}")

        bars: list[PriceBar] = []
        for day, values in series.items():
            try:
                bar_date = dt.date.fromisoformat(day)
            except ValueError:
                continue
            if not (start <= bar_date <= end):
                continue
            parsed = _parse_ohlcv(values)
            if parsed is None:
                continue
            open_, high, low, close, volume = parsed
            bars.append(
                PriceBar(
                    ts=dt.datetime.combine(bar_date, dt.time(0, 0), tzinfo=dt.UTC),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    interval=str(interval),
                    source=SOURCE,
                )
            )
        bars.sort(key=lambda bar: bar.ts)
        return bars

    def get_quote(self, ticker: str) -> Quote:
        payload = self._query({"function": "GLOBAL_QUOTE", "symbol": ticker})
        quote = payload.get("Global Quote")
        if not isinstance(quote, dict) or not quote:
            raise ProviderNotFoundError(f"Alpha Vantage returned no quote for {ticker!r}")

        price = _to_float(quote.get("05. price"))
        if price is None:
            raise ProviderDataError(f"Alpha Vantage quote for {ticker!r} has no price")

        change = _to_float(quote.get("09. change")) or 0.0
        change_percent = _to_float(str(quote.get("10. change percent", "")).rstrip("%")) or 0.0
        volume = _to_float(quote.get("06. volume")) or 0.0
        trading_day = quote.get("07. latest trading day")

        as_of = dt.datetime.now(dt.UTC)
        if isinstance(trading_day, str):
            try:
                as_of = dt.datetime.combine(
                    dt.date.fromisoformat(trading_day), dt.time(0, 0), tzinfo=dt.UTC
                )
            except ValueError:
                pass

        return Quote(
            ticker=ticker,
            price=price,
            change=change,
            change_percent=change_percent,
            volume=int(volume),
            as_of=as_of,
            source=SOURCE,
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        overview = self._overview(ticker)
        market_cap = _to_float(overview.get("MarketCapitalization"))
        return CompanyProfile(
            ticker=ticker,
            name=str(overview.get("Name") or ticker),
            exchange=str(overview.get("Exchange") or "UNKNOWN"),
            currency=str(overview.get("Currency") or "UNKNOWN"),
            source=SOURCE,
            sector=_optional_str(overview.get("Sector")),
            industry=_optional_str(overview.get("Industry")),
            market_cap=int(market_cap) if market_cap is not None else None,
        )

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        overview = self._overview(ticker)
        metrics = {}
        for source_key, metric_name in _OVERVIEW_METRICS.items():
            value = _to_float(overview.get(source_key))
            if value is not None:
                metrics[metric_name] = value

        return FundamentalsSnapshot(
            ticker=ticker,
            as_of_date=dt.datetime.now(dt.UTC).date(),
            metrics=metrics,
            source=SOURCE,
        )

    def health_check(self) -> bool:
        self._query({"function": "GLOBAL_QUOTE", "symbol": "IBM"})
        return True

    # -- internals ------------------------------------------------------------

    def _overview(self, ticker: str) -> dict[str, Any]:
        payload = self._query({"function": "OVERVIEW", "symbol": ticker})
        if not payload.get("Symbol"):
            raise ProviderNotFoundError(f"Alpha Vantage has no overview for {ticker!r}")
        return payload

    def _query(self, params: dict[str, str]) -> dict[str, Any]:
        payload = self._client.get_json("/query", params={**params, "apikey": self._api_key})

        # Alpha Vantage reports throttling and errors with HTTP 200 bodies.
        if "Note" in payload or "Information" in payload:
            message = payload.get("Note") or payload.get("Information")
            raise ProviderRateLimitError(f"Alpha Vantage throttled the request: {message}")
        if "Error Message" in payload:
            raise ProviderDataError(f"Alpha Vantage error: {payload['Error Message']}")
        return payload


def _parse_ohlcv(values: Any) -> tuple[float, float, float, float, int] | None:
    if not isinstance(values, dict):
        return None
    open_ = _to_float(values.get("1. open"))
    high = _to_float(values.get("2. high"))
    low = _to_float(values.get("3. low"))
    close = _to_float(values.get("4. close"))
    volume = _to_float(values.get("5. volume"))
    if None in (open_, high, low, close):
        return None
    return open_, high, low, close, int(volume or 0)  # type: ignore[return-value]


def _to_float(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip() and value.strip().lower() not in {"none", "n/a"}:
        return value.strip()
    return None
