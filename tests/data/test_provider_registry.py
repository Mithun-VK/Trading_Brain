from __future__ import annotations

import datetime as dt

import pytest

from data.ingestion.errors import ProviderError, ProviderRateLimitError, ProviderUnavailableError
from data.ingestion.mock_provider import MockProvider
from data.ingestion.provider import MarketDataProvider
from data.ingestion.registry import ProviderRegistry
from data.ingestion.schemas import CompanyProfile, FundamentalsSnapshot, PriceBar, Quote


class _StubProvider(MarketDataProvider):
    """Provider that either serves a canned quote or raises a chosen error."""

    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    def _maybe_raise(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error

    def get_quote(self, ticker: str) -> Quote:
        self._maybe_raise()
        return Quote(
            ticker=ticker,
            price=1.0,
            change=0.0,
            change_percent=0.0,
            volume=1,
            as_of=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            source=self.name,
        )

    def get_historical_prices(
        self, ticker: str, start: dt.date, end: dt.date, interval: str = "1d"
    ) -> list[PriceBar]:
        self._maybe_raise()
        return []

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        self._maybe_raise()
        return CompanyProfile(
            ticker=ticker, name=ticker, exchange="X", currency="USD", source=self.name
        )

    def get_fundamentals(self, ticker: str) -> FundamentalsSnapshot:
        self._maybe_raise()
        return FundamentalsSnapshot(ticker=ticker, as_of_date=dt.date(2026, 1, 1), source=self.name)

    def health_check(self) -> bool:
        self._maybe_raise()
        return True


def test_first_registered_provider_becomes_primary() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))

    assert registry.primary == "alpha"


def test_register_and_available() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))
    registry.register("beta", lambda: _StubProvider("beta"))

    assert registry.available() == ["alpha", "beta"]
    assert registry.is_registered("alpha")
    assert not registry.is_registered("gamma")


def test_switch_changes_primary() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))
    registry.register("beta", lambda: _StubProvider("beta"))

    registry.switch("beta")

    assert registry.primary == "beta"
    assert registry.get().get_quote("X").source == "beta"


def test_switch_to_unknown_provider_raises() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))

    with pytest.raises(ProviderError, match="Unknown market data provider"):
        registry.switch("nope")


def test_providers_are_instantiated_lazily_and_cached() -> None:
    constructions = []

    def factory() -> MarketDataProvider:
        constructions.append(1)
        return _StubProvider("alpha")

    registry = ProviderRegistry()
    registry.register("alpha", factory)
    assert constructions == []

    first = registry.get("alpha")
    second = registry.get("alpha")

    assert first is second
    assert len(constructions) == 1


def test_execute_falls_back_when_primary_fails() -> None:
    failing = _StubProvider("primary", error=ProviderUnavailableError("down"))
    healthy = _StubProvider("backup")

    registry = ProviderRegistry()
    registry.register("primary", lambda: failing)
    registry.register("backup", lambda: healthy)
    registry.set_fallbacks(["backup"])

    quote = registry.execute("get_quote", lambda p: p.get_quote("RELIANCE"))

    assert quote.source == "backup"
    assert failing.calls == 1
    assert healthy.calls == 1


def test_execute_falls_back_on_rate_limit() -> None:
    throttled = _StubProvider("primary", error=ProviderRateLimitError("x"))
    registry = ProviderRegistry()
    registry.register("primary", lambda: throttled)
    registry.register("backup", lambda: _StubProvider("backup"))
    registry.set_fallbacks(["backup"])

    assert registry.execute("get_quote", lambda p: p.get_quote("X")).source == "backup"


def test_execute_raises_last_error_when_all_providers_fail() -> None:
    first = _StubProvider("primary", error=ProviderUnavailableError("a"))
    second = _StubProvider("backup", error=ProviderUnavailableError("b"))
    registry = ProviderRegistry()
    registry.register("primary", lambda: first)
    registry.register("backup", lambda: second)
    registry.set_fallbacks(["backup"])

    with pytest.raises(ProviderUnavailableError, match="b"):
        registry.execute("get_quote", lambda p: p.get_quote("X"))


def test_synthetic_provider_is_rejected_as_a_fallback() -> None:
    """Rule 4: generated data must never silently stand in for real data."""
    registry = ProviderRegistry()
    registry.register("yahoo", lambda: _StubProvider("yahoo"))
    registry.register("mock", lambda: MockProvider(), synthetic=True)

    with pytest.raises(ProviderError, match="synthetic"):
        registry.set_fallbacks(["mock"])


def test_synthetic_provider_may_still_be_chosen_as_primary() -> None:
    registry = ProviderRegistry()
    registry.register("mock", lambda: MockProvider(), synthetic=True)
    registry.register("yahoo", lambda: _StubProvider("yahoo"))
    registry.switch("mock")

    assert registry.primary == "mock"
    assert registry.is_synthetic("mock")
    assert registry.get().get_quote("RELIANCE").source == "mock"


def test_health_check_reports_healthy_provider() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))

    health = registry.health_check("alpha")

    assert health.healthy
    assert health.name == "alpha"
    assert health.latency_ms is not None


def test_health_check_reports_failure_without_raising() -> None:
    broken = _StubProvider("alpha", error=ProviderUnavailableError("nope"))
    registry = ProviderRegistry()
    registry.register("alpha", lambda: broken)

    health = registry.health_check("alpha")

    assert not health.healthy
    assert "ProviderUnavailableError" in (health.error or "")


def test_health_check_all_covers_every_provider() -> None:
    registry = ProviderRegistry()
    registry.register("alpha", lambda: _StubProvider("alpha"))
    registry.register("mock", lambda: MockProvider(), synthetic=True)

    results = registry.health_check_all()

    assert {r.name for r in results} == {"alpha", "mock"}
    assert all(r.healthy for r in results)
    assert next(r for r in results if r.name == "mock").synthetic
