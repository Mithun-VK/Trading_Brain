# Market Data

`data/ingestion/provider.py` defines `MarketDataProvider`, the only
interface the rest of TradingBrain depends on:

```python
get_quote(ticker) -> Quote
get_historical_prices(ticker, start, end, interval="1d") -> list[PriceBar]
get_company_profile(ticker) -> CompanyProfile
get_fundamentals(ticker) -> FundamentalsSnapshot
```

Intervals are `Interval.DAILY` (`"1d"`), `WEEKLY` (`"1wk"`), and `MONTHLY`
(`"1mo"`) — the same strings stored in `prices.interval`.

## Providers

| Name | Class | Credentials | Notes |
|---|---|---|---|
| `mock` | `MockProvider` | none | Deterministic synthetic data. **Synthetic** — see the fallback rule below. |
| `yahoo` | `YahooFinanceProvider` | none | Yahoo's public chart/quoteSummary JSON over `httpx` (no `yfinance` dependency, so the transport stays injectable). |
| `alphavantage` | `AlphaVantageProvider` | `ALPHAVANTAGE_API_KEY` | Reports throttling in a **200-OK body** (`Note`/`Information`), translated to `ProviderRateLimitError` so it can't look like success. |

## Provider registry

`data/ingestion/registry.py`. `build_registry()` (in `factory.py`) wires it
from settings:

```env
MARKET_DATA_PROVIDER=yahoo          # primary
MARKET_DATA_FALLBACKS=alphavantage  # tried in order when the primary fails
MARKET_DATA_TIMEOUT_SECONDS=10
```

Capabilities: `register()` (lazy — registering a provider with missing
credentials costs nothing until used), `switch()`, `set_fallbacks()`,
`get()` (instantiate + cache), `execute()` (run an operation with fallback),
`health_check()` / `health_check_all()`.

**Safety property:** a provider registered `synthetic=True` (i.e. `mock`) is
**never** used as an automatic fallback — `set_fallbacks()` rejects it and
`execute()` skips it. Answering a request for real market data with
generated numbers would violate Rule 4. Mock can still be chosen
deliberately as the *primary*, which is the local-dev default.

`execute()` never invents a result: if every candidate fails it re-raises
the last `ProviderError`.

## Errors

`data/ingestion/errors.py` — `ProviderUnavailableError` (connection/timeout/
5xx, retried 3× with backoff), `ProviderRateLimitError` (subclass, so it is
also retryable/failover-able), `ProviderAuthError`, `ProviderDataError`,
`ProviderNotFoundError`. Adapters never leak raw `httpx` exceptions.

## Validation

`data/normalization/validation.py::validate_price_bars()` runs before
anything is persisted. Checks: missing/NaN values, non-positive prices,
`high < low`, `high` below the open/close body, `low` above it, negative
volume, future timestamps, and duplicate timestamps. Out-of-order bars are a
**warning** (they get sorted); everything else is an **error** and the bar is
**dropped, never repaired** — an interpolated price is fabricated data.

A bad bar doesn't poison the batch: good bars still flow through, and every
issue is persisted to `data_validation_errors`
(`data/storage/validation_repository.py`) so vendor problems stay auditable.

## Storage

`data/storage/price_repository.py`:

- `upsert_price_bars()` — **idempotent**. Existing `(asset_id, ts, interval)`
  rows are detected up front, so re-running a job is a no-op rather than an
  `IntegrityError`. Also de-duplicates within a single batch.
- `get_latest_bar_ts()` — the anchor for incremental fetches.
- `get_price_bars()` / `get_close_series()` — chronological reads in the
  shape the quant/regime engines expect.

Timestamps are compared on a normalized naive-UTC key, because SQLite (used
in tests) returns naive datetimes while PostgreSQL returns aware ones.

## Adding a real provider

1. Implement `MarketDataProvider` in `data/ingestion/<vendor>_provider.py`,
   reusing `HttpProviderClient` for timeout/retry/error mapping.
2. Register it in `factory.build_registry()`.
3. Never fabricate data on failure — raise, and let the registry fail over.

## Testing

`tests/data/` — every provider is tested against `httpx.MockTransport`, so
**CI never touches a live market API**. Coverage includes the registry
(switching, lazy construction, fallback, synthetic-fallback refusal, health
checks), both real adapters' happy paths and every error mapping, all
validation rules, and idempotent storage.
