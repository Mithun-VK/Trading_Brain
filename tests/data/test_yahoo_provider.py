from __future__ import annotations

import datetime as dt

import httpx
import pytest

from data.ingestion.errors import (
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from data.ingestion.yahoo_provider import YahooFinanceProvider

_CHART_META = {
    "currency": "INR",
    "symbol": "RELIANCE.NS",
    "exchangeName": "NSI",
    "fullExchangeName": "NSE",
    "instrumentType": "EQUITY",
    "regularMarketPrice": 1250.5,
    "chartPreviousClose": 1200.0,
    "regularMarketVolume": 5_000_000,
    "regularMarketTime": 1767225600,
    "longName": "Reliance Industries Limited",
}


def _chart_payload(
    timestamps: list[int] | None = None, quote: dict | None = None, meta: dict | None = None
) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": meta if meta is not None else _CHART_META,
                    "timestamp": timestamps if timestamps is not None else [],
                    "indicators": {"quote": [quote or {}]},
                }
            ],
            "error": None,
        }
    }


def _provider(handler) -> YahooFinanceProvider:
    return YahooFinanceProvider(transport=httpx.MockTransport(handler))


def test_get_historical_prices_parses_bars() -> None:
    payload = _chart_payload(
        timestamps=[1704153600, 1704240000],
        quote={
            "open": [100.0, 102.0],
            "high": [105.0, 107.0],
            "low": [99.0, 101.0],
            "close": [104.0, 106.0],
            "volume": [1000, 2000],
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v8/finance/chart/RELIANCE.NS" in request.url.path
        assert request.url.params["interval"] == "1d"
        return httpx.Response(200, json=payload)

    bars = _provider(handler).get_historical_prices(
        "RELIANCE.NS", dt.date(2024, 1, 1), dt.date(2024, 1, 3)
    )

    assert len(bars) == 2
    assert bars[0].open == 100.0
    assert bars[0].close == 104.0
    assert bars[0].volume == 1000
    assert bars[0].interval == "1d"
    assert all(bar.source == "yahoo" for bar in bars)


def test_get_historical_prices_drops_null_bars_rather_than_interpolating() -> None:
    payload = _chart_payload(
        timestamps=[1704153600, 1704240000, 1704326400],
        quote={
            "open": [100.0, None, 102.0],
            "high": [105.0, None, 107.0],
            "low": [99.0, None, 101.0],
            "close": [104.0, None, 106.0],
            "volume": [1000, None, 2000],
        },
    )

    bars = _provider(lambda r: httpx.Response(200, json=payload)).get_historical_prices(
        "X", dt.date(2024, 1, 1), dt.date(2024, 1, 5)
    )

    assert len(bars) == 2
    assert [bar.close for bar in bars] == [104.0, 106.0]


def test_get_historical_prices_maps_weekly_interval() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["interval"] = request.url.params["interval"]
        return httpx.Response(200, json=_chart_payload())

    _provider(handler).get_historical_prices(
        "X", dt.date(2024, 1, 1), dt.date(2024, 2, 1), interval="1wk"
    )

    assert captured["interval"] == "1wk"


def test_get_historical_prices_rejects_unsupported_interval() -> None:
    with pytest.raises(NotImplementedError):
        _provider(lambda r: httpx.Response(200, json=_chart_payload())).get_historical_prices(
            "X", dt.date(2024, 1, 1), dt.date(2024, 1, 2), interval="1h"
        )


def test_get_historical_prices_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="start must not be after end"):
        _provider(lambda r: httpx.Response(200, json=_chart_payload())).get_historical_prices(
            "X", dt.date(2024, 2, 1), dt.date(2024, 1, 1)
        )


def test_get_quote_derives_change_from_previous_close() -> None:
    quote = _provider(lambda r: httpx.Response(200, json=_chart_payload())).get_quote("RELIANCE.NS")

    assert quote.price == 1250.5
    assert quote.change == pytest.approx(50.5)
    assert quote.change_percent == pytest.approx(50.5 / 1200.0 * 100)
    assert quote.source == "yahoo"


def test_get_quote_raises_when_price_missing() -> None:
    payload = _chart_payload(meta={"currency": "INR"})

    with pytest.raises(Exception, match="regularMarketPrice"):
        _provider(lambda r: httpx.Response(200, json=payload)).get_quote("X")


def test_unknown_symbol_raises_not_found() -> None:
    payload = {
        "chart": {
            "result": None,
            "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"},
        }
    }

    with pytest.raises(ProviderNotFoundError, match="delisted"):
        _provider(lambda r: httpx.Response(200, json=payload)).get_quote("NOPE")


def test_rate_limit_maps_to_rate_limit_error() -> None:
    with pytest.raises(ProviderRateLimitError):
        _provider(lambda r: httpx.Response(429)).get_quote("X")


def test_auth_failure_maps_to_auth_error() -> None:
    with pytest.raises(ProviderAuthError):
        _provider(lambda r: httpx.Response(401)).get_quote("X")


def test_server_error_maps_to_unavailable_and_retries() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderUnavailableError):
        _provider(handler).get_quote("X")

    assert len(attempts) == 3  # retried per the shared client policy


def test_timeout_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ProviderUnavailableError):
        _provider(handler).get_quote("X")


def test_get_company_profile_reports_missing_fields_as_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "quoteSummary" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "quoteSummary": {
                        "result": [{"assetProfile": {}, "summaryDetail": {}, "price": {}}],
                        "error": None,
                    }
                },
            )
        return httpx.Response(200, json=_chart_payload())

    profile = _provider(handler).get_company_profile("RELIANCE.NS")

    assert profile.name == "Reliance Industries Limited"
    assert profile.exchange == "NSE"
    assert profile.currency == "INR"
    assert profile.sector is None
    assert profile.market_cap is None


def test_get_company_profile_uses_quote_summary_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "quoteSummary" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "quoteSummary": {
                        "result": [
                            {
                                "assetProfile": {"sector": "Energy", "industry": "Refining"},
                                "summaryDetail": {"marketCap": {"raw": 1_700_000_000_000}},
                                "price": {"longName": "Reliance Industries Ltd"},
                            }
                        ],
                        "error": None,
                    }
                },
            )
        return httpx.Response(200, json=_chart_payload())

    profile = _provider(handler).get_company_profile("RELIANCE.NS")

    assert profile.sector == "Energy"
    assert profile.industry == "Refining"
    assert profile.market_cap == 1_700_000_000_000


def test_get_fundamentals_extracts_and_snake_cases_metrics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quoteSummary": {
                    "result": [
                        {
                            "summaryDetail": {"trailingPE": {"raw": 24.5}, "beta": {"raw": 1.1}},
                            "financialData": {"returnOnEquity": {"raw": 0.18}},
                        }
                    ],
                    "error": None,
                }
            },
        )

    fundamentals = _provider(handler).get_fundamentals("RELIANCE.NS")

    assert fundamentals.metrics["pe_ratio"] == 24.5
    assert fundamentals.metrics["beta"] == 1.1
    assert fundamentals.metrics["return_on_equity"] == 0.18
    assert fundamentals.source == "yahoo"


def test_health_check_returns_true_when_reachable() -> None:
    assert _provider(lambda r: httpx.Response(200, json=_chart_payload())).health_check() is True
