# TradingBrain

TradingBrain is an AI-assisted personal trading and investment intelligence
platform. It is **not** an autonomous trading bot: this phase of the project
builds a research and reasoning foundation, with broker execution explicitly
disabled.

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

## Current status: Phase 3 complete (PostgreSQL data layer)

What exists today:

- Monorepo layout (`apps/`, `brain/`, `quant/`, `data/`, `integrations/`,
  `models/`, `config/`, `tests/`, `scripts/`, `docs/`, `docker/`, `vault/`)
- FastAPI app skeleton (`apps/api`) with a `/health` endpoint, structured
  request logging, and a hard guard that rejects any `/orders`, `/execute`,
  `/buy`, `/sell` path with `403` (defense-in-depth for Rule 8 — no such
  routes exist, and none will be added until execution is explicitly
  approved in a much later phase)
- Worker process skeleton (`apps/worker`) — no jobs yet
- Centralized settings (`config/settings.py`) and structured logging
  (`config/logging.py`) with automatic secret redaction
- Obsidian vault spec (`vault/`) with folder structure and the four required
  note templates, plus a `KnowledgeStore`/`ObsidianKnowledgeStore`
  integration over the Local REST API plugin (search/read/write/update/
  append/list/backlinks) — see [docs/obsidian.md](docs/obsidian.md)
- PostgreSQL schema (12 tables) via SQLAlchemy models + Alembic migrations —
  see [docs/database.md](docs/database.md)
- Docker Compose stack: API, worker, PostgreSQL, Redis
- Test suite runnable with a single `pytest` command

What is intentionally **not** implemented yet (later phases): market data
providers, quant indicators, market regime engine, Claude research/thesis
agents, trading journal review, remaining API endpoints, and the Next.js
dashboard.

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

Not yet implemented (Phase 7). `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` are
reserved in `.env.example`. The model name is read from configuration and is
never hard-coded.

## Current limitations

- Nothing populates the database yet — schema exists, no ingestion.
- No market data, quant, or regime logic yet.
- No Claude integration yet.
- No broker execution, and none is planned until the full research/thesis/
  quant/risk/audit/paper-trading stack is independently validated (see
  [docs/architecture.md](docs/architecture.md), Critical Design Rules).

## Future phases

Market data abstraction → quantitative engine → market regime engine →
Claude research layer → context pipeline → research agent → thesis agent →
trading journal intelligence → remaining API endpoints → dashboard. See
[docs/architecture.md](docs/architecture.md) for details on each phase.

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
