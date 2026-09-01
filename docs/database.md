# Database (PostgreSQL)

PostgreSQL is the **structured-data layer** — prices, fundamentals, trades,
signals, and regime observations. It does not store research prose or
theses text; those live in Obsidian, with a lightweight pointer row here
(`obsidian_note_path`) so they're joinable from SQL.

## Schema

Models: [`models/`](../models/). Migrations: [`alembic/versions/`](../alembic/versions/).

| Table | Purpose |
|---|---|
| `assets` | One row per tradeable instrument (ticker + exchange unique). |
| `companies` | Equity-specific metadata for an asset (1:1 with `assets`). |
| `prices` | OHLCV bars, unique per `(asset_id, ts, interval)`. Immutable — corrections are new rows, not updates. |
| `financial_metrics` | Fundamental data points, unique per `(asset_id, metric_name, period, as_of_date)`. |
| `market_events` | Notable market-moving events, optionally linked to an asset. |
| `market_regimes` | Point-in-time output of `quant.regime.detector.MarketRegimeDetector` (Phase 6). |
| `strategies` | Named strategy definitions referenced by trades. |
| `trades` | One row per trade, with risk/R-multiple fields and a pointer to its Obsidian note. |
| `positions` | Current/historical portfolio holdings. |
| `signals` | Deterministic quant outputs (Rule 1/Rule 2 — never a Claude output). |
| `research_documents` | Pointer + metadata for Research Agent output (Phase 8). |
| `theses` | Pointer + metadata for an Investment Thesis; `current_assessment` changes must correspond to an audit entry in the Obsidian note (Rule 9). |

## Migrations

Managed with Alembic, driven by `config.settings.get_settings().database_url`
(not `alembic.ini`) so there is one source of truth for the connection
string.

```bash
# apply all migrations
alembic upgrade head

# generate SQL without touching a database (useful for review)
alembic upgrade head --sql

# create a new migration after changing models/
alembic revision --autogenerate -m "describe the change"
```

## Local setup

```bash
docker compose up -d postgres
alembic upgrade head
```

Or point `DATABASE_URL` at any PostgreSQL 16 instance.

## Testing

Model/relationship tests (`tests/models/`) run against an in-memory SQLite
engine via `Base.metadata.create_all` — no PostgreSQL instance required.
This validates ORM correctness (FKs, constraints, relationships) but is not
a substitute for running `alembic upgrade head` against real PostgreSQL
before deploying a schema change.
