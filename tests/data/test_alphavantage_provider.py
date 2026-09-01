from __future__ import annotations

import datetime as dt

import httpx
import pytest

from data.ingestion.alphavantage_provider import AlphaVantageProvider
from data.ingestion.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)

_DAILY_SERIES = {
    "Time Series (Daily)": {
        "2024-01-03": {
            "1. open": "102.0",
            "2. high": "107.0",
            "3. low": "101.0",
            "4. close": "106.0",
            "5. volume": "2000",
        },
        "2024-01-02": {
            "1. open": "100.0",
            "2. high": "105.0",
            "3. low": "99.0",
            "4. close": "104.0",
            "5. volume": "1000",
        },
        "2023-12-01": {
            "1. open": "90.0",
            "2. high": "95.0",
            "3. low": "89.0",
            "4. close": "94.0",
            "5. volume": "500",
        },
    }
}


def _provider(handler) -> AlphaVantageProvider:
    return AlphaVantageProvider(api_key="test-key", transport=httpx.MockTransport(handler))


def test_requires_api_key() -> None:
    with pytest.raises(ProviderAuthError):
        AlphaVantageProvider(api_key="")


def test_get_historical_prices_filters_range_and_sorts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["function"] == "TIME_SERIES_DAILY"
        assert request.url.params["apikey"] == "test-key"
        return httpx.Response(200, json=_DAILY_SERIES)

    bars = _provider(handler).get_historical_prices(
        "IBM", dt.date(2024, 1, 1), dt.date(2024, 1, 31)
    )

    assert len(bars) == 2  # the 2023-12-01 bar is outside the requested range
    assert bars[0].ts < bars[1].ts
    assert bars[0].close == 104.0
    assert all(bar.source == "alphavantage" for bar in bars)


def test_weekly_interval_uses_weekly_function() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["function"] = request.url.params["function"]
        return httpx.Response(200, json={"Weekly Time Series": {}})

    _provider(handler).get_historical_prices(
        "IBM", dt.date(2024, 1, 1), dt.date(2024, 2, 1), interval="1wk"
    )

    assert captured["function"] == "TIME_SERIES_WEEKLY"


def test_unsupported_interval_raises() -> None:
    with pytest.raises(NotImplementedError):
        _provider(lambda r: httpx.Response(200, json={})).get_historical_prices(
            "IBM", dt.date(2024, 1, 1), dt.date(2024, 1, 2), interval="5m"
        )


def test_get_quote_parses_global_quote() -> None:
    payload = {
        "Global Quote": {
            "01. symbol": "IBM",
            "05. price": "123.45",
            "06. volume": "1000000",
            "07. latest trading day": "2024-01-03",
            "09. change": "1.45",
            "10. change percent": "1.1885%",
        }
    }

    quote = _provider(lambda r: httpx.Response(200, json=payload)).get_quote("IBM")

    assert quote.price == 123.45
    assert quote.change == 1.45
    assert quote.change_percent == pytest.approx(1.1885)
    assert quote.volume == 1_000_000
    assert quote.as_of.date() == dt.date(2024, 1, 3)


def test_throttling_note_maps_to_rate_limit_error() -> None:
    """Alpha Vantage throttles with HTTP 200 -- it must not look like success."""
    payload = {"Note": "Our standard API call frequency is 5 calls per minute"}

    with pytest.raises(ProviderRateLimitError):
        _provider(lambda r: httpx.Response(200, json=payload)).get_quote("IBM")


def test_information_key_also_maps_to_rate_limit_error() -> None:
    payload = {"Information": "Thank you for using Alpha Vantage!"}

    with pytest.raises(ProviderRateLimitError):
        _provider(lambda r: httpx.Response(200, json=payload)).get_quote("IBM")


def test_error_message_maps_to_data_error() -> None:
    payload = {"Error Message": "Invalid API call."}

    with pytest.raises(ProviderDataError):
        _provider(lambda r: httpx.Response(200, json=payload)).get_quote("IBM")


def test_missing_quote_raises_not_found() -> None:
    with pytest.raises(ProviderNotFoundError):
        _provider(lambda r: httpx.Response(200, json={"Global Quote": {}})).get_quote("NOPE")


def test_get_company_profile_and_fundamentals() -> None:
    overview = {
        "Symbol": "IBM",
        "Name": "International Business Machines",
        "Exchange": "NYSE",
        "Currency": "USD",
        "Sector": "TECHNOLOGY",
        "Industry": "None",
        "MarketCapitalization": "160000000000",
        "PERatio": "22.5",
        "EPS": "8.1",
    }
    provider = _provider(lambda r: httpx.Response(200, json=overview))

    profile = provider.get_company_profile("IBM")
    fundamentals = provider.get_fundamentals("IBM")

    assert profile.sector == "TECHNOLOGY"
    assert profile.industry is None  # "None" string is not a real value
    assert profile.market_cap == 160_000_000_000
    assert fundamentals.metrics == {"pe_ratio": 22.5, "eps": 8.1}
