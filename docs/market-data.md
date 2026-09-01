# Market Data

`data/ingestion/provider.py` defines `MarketDataProvider`, the only
interface the rest of TradingBrain depends on:

```python
get_quote(ticker) -> Quote
get_historical_prices(ticker, start, end, interval="1d") -> list[PriceBar]
get_company_profile(ticker) -> CompanyProfile
get_fundamentals(ticker) -> FundamentalsSnapshot
```

`data/ingestion/factory.get_market_data_provider(name)` selects an
implementation by name (`config.settings.market_data_provider`,
`MARKET_DATA_PROVIDER` env var). Only `"mock"` exists today.

## MockProvider

`data/ingestion/mock_provider.py`. Requires no API key. Every value it
returns is tagged `source="mock"` — Rule 4 (never fabricate live financial
data and present it as real) applies to how callers treat this: do not
render mock data in a UI or Obsidian note without the `mock` label visible.

Deterministic by design: each ticker seeds an independent random walk
anchored at a fixed epoch (2000-01-01), so the same ticker/date range always
returns identical bars, in the same process or a different one. This makes
it usable both for manual exploration and as a fixture in tests for the
quant/regime/research layers built on top of it.

## Normalization

`data/normalization/prices.py` maps a provider `PriceBar` to a `models.Price`
row. This is the only place that construction happens, so provider output
never leaks into persistence code ad hoc.

## Adding a real provider

1. Implement `MarketDataProvider` in a new `data/ingestion/<vendor>_provider.py`.
2. Add a branch in `get_market_data_provider`.
3. Never fabricate data on API failure — raise, don't silently fall back to
   mock data in a way that could be mistaken for real prices.
