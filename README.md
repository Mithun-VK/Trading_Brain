# TradingBrain

TradingBrain is an AI-assisted personal trading and investment intelligence
platform. It is **not** an autonomous trading bot: it is a research and
reasoning foundation, with broker execution explicitly and permanently
disabled until a much later, independently-validated phase.

```text
PostgreSQL   = structured financial data
Obsidian     = long-term knowledge / memory
Python       = deterministic quantitative analysis
Claude       = reasoning / research layer
TradingBrain API = orchestration layer
Broker execution = disabled in this phase
```

See [docs/architecture.md](docs/architecture.md) for the full system design
and phase roadmap.

## Current status: all 13 phases of the initial plan are complete

What exists today:

- Monorepo layout (`apps/`, `brain/`, `quant/`, `data/`, `integrations/`,
  `models/`, `config/`, `tests/`, `scripts/`, `docs/`, `docker/`, `vault/`)
- FastAPI app (`apps/api`) with every endpoint from the spec except broker
  execution — see [docs/api.md](docs/api.md). A hard middleware guard
  rejects any `/orders`, `/execute`, `/buy`, `/sell` path with `403`
  regardless of whether a route is ever registered for it (Rule 8)
- Worker process skeleton (`apps/worker`) — no scheduled jobs yet
- Centralized settings (`config/settings.py`) and structured logging
  (`config/logging.py`) with automatic secret redaction
- Obsidian vault spec (`vault/`) with folder structure and the four required
  note templates, plus a `KnowledgeStore`/`ObsidianKnowledgeStore`
  integration over the Local REST API plugin — see [docs/obsidian.md](docs/obsidian.md)
- PostgreSQL schema (12 tables) via SQLAlchemy models + Alembic migrations —
  see [docs/database.md](docs/database.md)
- `MarketDataProvider` abstraction with a deterministic `MockProvider`
  (no API key required) — see [docs/market-data.md](docs/market-data.md)
- Deterministic quant engine: technical indicators, risk math, performance
  stats, and a rule-based market regime detector — see [docs/quant-engine.md](docs/quant-engine.md)
- `LLMProvider`/`ClaudeProvider` (Anthropic SDK), a targeted context
  assembler, a Research Agent, a Thesis Agent, and a Trading Journal Review
  Agent — see [docs/claude.md](docs/claude.md), [docs/research-agents.md](docs/research-agents.md),
  [docs/thesis-engine.md](docs/thesis-engine.md), [docs/trading-journal.md](docs/trading-journal.md)
- Docker Compose stack: API, worker, PostgreSQL, Redis
- Next.js/TypeScript dashboard (`apps/dashboard`) — a thin client over the
  API with no direct database/Obsidian/Claude access, covering every
  section from the spec
- 130 backend tests + a clean `next build`/`npm run lint`, all passing
  without a live database, Obsidian instance, or Anthropic API key
  (fakes/mocks throughout — see each doc's Testing section)

What is intentionally **not** implemented, deliberately and indefinitely:
broker execution. No autonomous trading exists or is planned until the
full research/thesis/quant/risk/audit/paper-trading stack is independently
validated (Critical Design Rules in [docs/architecture.md](docs/architecture.md)).

## Installation

Requirements: Python 3.11+ (3.12+ recommended — see
[Assumptions](#assumptions-from-phase-0)), Docker Desktop (optional, for the
full stack), Git.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Environment variables

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.
See `.env.example` for the full list (app, PostgreSQL, Redis, Obsidian,
Anthropic/Claude, market data provider selection).

## Running locally (without Docker)

```bash
uvicorn apps.api.main:app --reload
```

Then visit `http://localhost:8000/health`.

The worker is currently a no-op skeleton:

```bash
python -m apps.worker.main
```

## Running with Docker

```bash
docker compose up -d
docker compose ps
docker compose logs -f api
docker compose down
```

This starts PostgreSQL, Redis, the API, and the worker. The API is exposed
on `http://localhost:8000`.

## Running tests

```bash
pytest
```

No Docker or database is required for the current test suite — it exercises
the FastAPI app in-process.

## Running the dashboard

```bash
cd apps/dashboard
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to :8000
npm run dev
```

Visit `http://localhost:3000`. See [docs/development.md](docs/development.md).

## Obsidian setup

See [vault/README.md](vault/README.md) for vault setup (Local REST API
plugin, `.env` values) and [docs/obsidian.md](docs/obsidian.md) for the
integration architecture. Verify with:

```bash
python -m scripts.test_obsidian
```

## Database setup

```bash
docker compose up -d postgres
alembic upgrade head
```

See [docs/database.md](docs/database.md) for the schema and migration
workflow.

## Claude setup

Set `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in `.env`. The model name is
always read from configuration — never hard-coded. See [docs/claude.md](docs/claude.md).

## Current limitations

- No real market data provider yet — only the deterministic `MockProvider`.
  Nothing fabricated by it should ever be treated as real (Rule 4). Adding a
  real vendor means one new `data/ingestion/<vendor>_provider.py` plus a
  branch in `get_market_data_provider` — see [docs/market-data.md](docs/market-data.md).
- The worker has no scheduled jobs yet (no periodic ingestion/regime
  refresh) — everything runs on-demand via the API.
- The dashboard has no watchlist backend (stored in browser `localStorage`
  only, clearly labeled as such) and no auth — it's a local development
  tool, not deployed anywhere.
- No broker execution, and none is planned until the full research/thesis/
  quant/risk/audit/paper-trading stack is independently validated (see
  [docs/architecture.md](docs/architecture.md), Critical Design Rules).

## Future work

All 13 phases from the original implementation plan are complete. Natural
next steps beyond the plan: a real market data provider, scheduled worker
jobs (periodic price ingestion, regime refresh), a watchlist table, and —
only after independent validation of the full stack — paper trading.

## Assumptions from Phase 0

- The local environment has Python 3.11.9. `pyproject.toml` declares
  `requires-python = ">=3.11"` for local development compatibility; Docker
  images pin `python:3.12-slim` so containerized runs use the preferred
  3.12+ runtime. Upgrading the local interpreter to 3.12+ is recommended but
  not required to run this phase.
- Dependency management uses `pip` + `pyproject.toml` (PEP 621, `hatchling`
  backend) rather than Poetry or `uv`, since neither was available in the
  environment and stdlib `venv` + `pip` has zero setup cost.
- `psycopg` (v3) is used as the PostgreSQL driver over `psycopg2`, matching
  current SQLAlchemy 2.x recommendations.
- No repository existed prior to this phase (confirmed empty directory) and
  no `git` repository was initialized; this phase initializes one.
