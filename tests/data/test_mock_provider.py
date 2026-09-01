from __future__ import annotations

import datetime as dt

import pytest

from data.ingestion.factory import get_market_data_provider
from data.ingestion.mock_provider import MockProvider


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


def test_historical_prices_are_deterministic(provider: MockProvider) -> None:
    start, end = dt.date(2024, 1, 1), dt.date(2024, 3, 1)

    first = provider.get_historical_prices("RELIANCE", start, end)
    second = provider.get_historical_prices("RELIANCE", start, end)

    assert first == second
    assert len(first) > 0


def test_historical_prices_differ_by_ticker(provider: MockProvider) -> None:
    start, end = dt.date(2024, 1, 1), dt.date(2024, 2, 1)

    reliance = provider.get_historical_prices("RELIANCE", start, end)
    tcs = provider.get_historical_prices("TCS", start, end)

    assert [b.close for b in reliance] != [b.close for b in tcs]


def test_historical_prices_excludes_weekends(provider: MockProvider) -> None:
    bars = provider.get_historical_prices("INFY", dt.date(2024, 1, 1), dt.date(2024, 1, 7))

    assert all(bar.ts.weekday() < 5 for bar in bars)


def test_historical_prices_all_tagged_mock(provider: MockProvider) -> None:
    bars = provider.get_historical_prices("INFY", dt.date(2024, 1, 1), dt.date(2024, 1, 31))

    assert all(bar.source == "mock" for bar in bars)


def test_get_historical_prices_rejects_bad_range(provider: MockProvider) -> None:
    with pytest.raises(ValueError, match="start must not be after end"):
        provider.get_historical_prices("INFY", dt.date(2024, 2, 1), dt.date(2024, 1, 1))


def test_get_historical_prices_rejects_unsupported_interval(provider: MockProvider) -> None:
    with pytest.raises(NotImplementedError):
        provider.get_historical_prices("INFY", dt.date(2024, 1, 1), dt.date(2024, 1, 2), "1h")


def test_get_quote_derives_from_history(provider: MockProvider) -> None:
    quote = provider.get_quote("RELIANCE")

    assert quote.ticker == "RELIANCE"
    assert quote.price > 0
    assert quote.source == "mock"


def test_get_company_profile_is_deterministic(provider: MockProvider) -> None:
    first = provider.get_company_profile("RELIANCE")
    second = provider.get_company_profile("RELIANCE")

    assert first == second
    assert first.source == "mock"


def test_get_fundamentals_is_tagged_mock(provider: MockProvider) -> None:
    fundamentals = provider.get_fundamentals("RELIANCE")

    assert fundamentals.source == "mock"
    assert "pe_ratio" in fundamentals.metrics


def test_factory_returns_mock_provider() -> None:
    assert isinstance(get_market_data_provider("mock"), MockProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(NotImplementedError):
        get_market_data_provider("some_real_vendor")
