# TradingBrain API

FastAPI app: `apps/api/main.py`. Routers under `apps/api/routers/`.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness check. |
| GET | `/assets/{ticker}` | Asset + company metadata from PostgreSQL. 404 if unknown. |
| GET | `/market/{ticker}` | Latest quote via the configured `MarketDataProvider`. |
| GET | `/market/regime` | Most recent `market_regimes` row. Registered *before* `/market/{ticker}` — otherwise `regime` would be captured as a ticker. |
| GET | `/analysis/{ticker}` | Deterministic quant summary + latest regime. No Obsidian dependency. |
| POST | `/research/{ticker}` | Runs the Research Agent, publishes to Obsidian, returns the `ResearchAnalysis`. 404 if the ticker has no `assets` row yet. |
| GET | `/thesis/{ticker}` | The active thesis for a ticker. 404 if none. |
| POST | `/thesis/{ticker}/review` | Runs the Thesis Agent's `review_and_apply` — writes the audit entry and updates `current_assessment`. |
| GET | `/trades` | List trades, optional `ticker`/`status` query filters. |
| POST | `/trades` | **Journal** a trade that already happened/was planned — not an order. Auto-registers a new strategy name on first use. |
| POST | `/trades/{id}/review` | Runs the Trade Journal Review Agent over a single trade (sample size will correctly show `n=1`). |
| GET | `/portfolio/summary` | Open trade count, open exposure value, counts by status. |

## What does not exist, on purpose

`POST /orders`, `/execute`, `/buy`, `/sell` — and never will in this phase.
They are blocked at the middleware layer in `apps/api/main.py`
(`_BLOCKED_PATH_PREFIXES`) regardless of whether a route is ever
registered for them (Rule 8) — see `tests/test_broker_execution_disabled.py`.

## Dependencies (`apps/api/dependencies.py`)

- `get_session` — DB session per request (`data.storage.session.get_db`).
- `get_market_data` — provider selected by `MARKET_DATA_PROVIDER`.
- `get_knowledge_store` — `ObsidianKnowledgeStore`; returns `503` if
  `OBSIDIAN_API_KEY` isn't configured, rather than a raw exception.
- `get_llm_provider` — `ClaudeProvider`; returns `503` if
  `ANTHROPIC_API_KEY` isn't configured.

## Testing

`tests/apps/api/` overrides all four dependencies with in-memory/fake
implementations (`tests/fakes.py`, `MockProvider`, a `StaticPool` SQLite
engine shared across requests within a test) — no live Postgres, Obsidian,
or Anthropic API key required.
