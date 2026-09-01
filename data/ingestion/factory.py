"""Provider selection.

`build_registry()` is the real entry point from Phase 14 onward;
`get_market_data_provider(name)` is kept as the simple single-provider
accessor that existing callers (API dependencies, tests) already use.
"""

from __future__ import annotations

from config.settings import Settings, get_settings
from data.ingestion.alphavantage_provider import AlphaVantageProvider
from data.ingestion.mock_provider import MockProvider
from data.ingestion.provider import MarketDataProvider
from data.ingestion.registry import ProviderRegistry
from data.ingestion.yahoo_provider import YahooFinanceProvider

MOCK = "mock"
YAHOO = "yahoo"
ALPHAVANTAGE = "alphavantage"


def get_market_data_provider(provider_name: str) -> MarketDataProvider:
    """Construct a single provider by name, using ambient settings for any
    credentials it needs.
    """
    return _construct(provider_name, get_settings())


def build_registry(settings: Settings | None = None) -> ProviderRegistry:
    """Build the registry described by settings: every known provider is
    registered (lazily), the configured primary is selected, and any
    configured fallbacks are wired in.
    """
    settings = settings or get_settings()
    registry = ProviderRegistry()

    registry.register(MOCK, lambda: MockProvider(), synthetic=True)
    registry.register(YAHOO, lambda: _construct(YAHOO, settings))
    registry.register(ALPHAVANTAGE, lambda: _construct(ALPHAVANTAGE, settings))

    registry.switch(settings.market_data_provider)
    if settings.market_data_fallback_list:
        registry.set_fallbacks(settings.market_data_fallback_list)
    return registry


def _construct(provider_name: str, settings: Settings) -> MarketDataProvider:
    if provider_name == MOCK:
        return MockProvider()
    if provider_name == YAHOO:
        return YahooFinanceProvider(timeout=settings.market_data_timeout_seconds)
    if provider_name == ALPHAVANTAGE:
        return AlphaVantageProvider(
            api_key=settings.alphavantage_api_key,
            timeout=settings.market_data_timeout_seconds,
        )
    raise NotImplementedError(
        f"Market data provider {provider_name!r} is not implemented. "
        f"Available: {MOCK}, {YAHOO}, {ALPHAVANTAGE}."
    )
