"""Provider selection. Adding a real vendor later means adding one branch
here plus a new adapter module — callers keep depending on
`MarketDataProvider` and never import a concrete provider directly.
"""

from __future__ import annotations

from data.ingestion.mock_provider import MockProvider
from data.ingestion.provider import MarketDataProvider


def get_market_data_provider(provider_name: str) -> MarketDataProvider:
    if provider_name == "mock":
        return MockProvider()
    raise NotImplementedError(
        f"Market data provider {provider_name!r} is not implemented. "
        "Only 'mock' is available in this phase."
    )
