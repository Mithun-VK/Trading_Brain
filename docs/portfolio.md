# Watchlists & Paper Portfolio

## Watchlists

Tables: `watchlists`, `watchlist_items`. Repository:
`data/storage/watchlist_repository.py`.

A watchlist is a named set of assets with a `kind` (`theme` | `sector` |
`personal`) — e.g. *AI*, *Indian Manufacturing*, *Banking*, *High
Conviction*. They're database rows, not browser state, because they drive
what the ingestion and research engines prioritize.

- An asset can belong to many watchlists.
- `add_item()` is idempotent: re-adding updates the note rather than
  creating a duplicate (there's also a DB-level unique constraint).
- Deleting a watchlist cascades to its items.
- `get_watched_asset_ids()` returns the deduplicated union — the hook
  later phases use to scope work to what you actually care about.

> The dashboard's Phase 13 watchlist page stored tickers in `localStorage`.
> That page can now be backed by these endpoints; the browser-local version
> remains only as a fallback.

## Paper portfolio

Tables: `paper_portfolios`, `paper_positions`, `paper_transactions`.

**There is no broker connectivity anywhere in this system.** These rows
record simulated positions; nothing here places, routes, or settles a real
order (Rule 8).

### Separation of concerns

| Layer | Where | Responsibility |
|---|---|---|
| Accounting math | `quant/performance/portfolio.py` | Pure functions. No DB, no clock, no I/O. |
| Persistence | `data/storage/portfolio_repository.py` | Load state → apply math → write rows + ledger entry. |

Rule 2 again: the numbers that gate a human decision are computed by
deterministic, unit-tested functions — not inferred anywhere else.

### Accounting conventions

Stated explicitly because they change the numbers:

- Fees are **capitalized into cost basis** on a buy, **deducted from
  proceeds** on a sell.
- Average cost is **unchanged by a sell** (standard average-cost method);
  only quantity and realized P&L move.
- A fully-closed position keeps its row with `quantity = 0`, so cumulative
  realized P&L **survives a re-entry**.
- **Long-only.** Overselling raises `InsufficientPositionError` rather than
  silently opening a short.
- Buying beyond the cash balance raises `InsufficientCashError` — a paper
  portfolio that can spend money it doesn't have teaches the wrong lesson.

### The ledger is the source of truth

`paper_transactions` is append-only. Position state is always reproducible
by replaying it, and tests assert the cash balance reconciles with the sum
of `cash_delta` across the ledger.

### Valuation

`value_portfolio(session, portfolio, prices)` takes a `{ticker: price}` map
and returns cash, positions value, total equity, exposure, per-position
allocation, realized and unrealized P&L, and total return.

**Unpriced positions are reported, not guessed.** A position with no
supplied price is counted in `unpriced_positions` and excluded from market
value rather than being valued at its cost basis — presenting a stale cost
as a current value would be fabricated data (Rule 4).

### Monetary precision

Values are stored in `Numeric(18, 6)` and the pure functions round to the
same 6 dp, so in-memory and persisted state can't drift apart. Float
arithmetic is deterministic (same inputs → same outputs); exact decimal
arithmetic would be the stricter choice and is a reasonable future change,
but mixing conventions mid-codebase would be worse.

## Testing

`tests/quant/test_portfolio_math.py` — hand-worked reference values for
averaging, fee treatment, partial/full sells, accumulated realized P&L, and
every guard. `tests/data/test_watchlist_repository.py` and
`tests/data/test_portfolio_repository.py` cover persistence, idempotency,
cash reconciliation, re-entry, and unpriced-position handling. No live
database required — all SQLite in-memory.
