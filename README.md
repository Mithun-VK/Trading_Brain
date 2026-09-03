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

## Current status: all 45 phases complete

TradingBrain now runs as a continuous intelligence loop: it ingests market
data on a schedule, notices what changed, researches what matters, forms and
reviews theses, emits evidence-backed signals, simulates positions on paper,
and grades its own past reasoning against what actually happened.

**Verified:** 696 backend tests · mypy clean (164 source files) · ruff clean
· eslint clean · `next build` clean (18 routes) · 10 migrations applying from
an empty database with no schema drift.

Read [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) before
deploying this anywhere. It rates each category GREEN/YELLOW/RED and is
written to be useful rather than reassuring.

### What exists

**Foundation** — monorepo layout, FastAPI app, worker, centralized settings,
structured logging with automatic secret redaction, PostgreSQL schema (25
tables) via SQLAlchemy + Alembic, Obsidian vault integration over the Local
REST API plugin, deterministic quant engine, and the Claude reasoning layer
(Research, Thesis, and Journal Review agents).

**Continuous intelligence** — real market data providers (Yahoo, Alpha
Vantage) with fallback, 8 scheduled jobs, watchlists and a paper portfolio,
a change-detection research queue, an anti-lookahead backtesting engine, an
evidence-backed signal engine, paper trading, and a learning loop that
scores past reasoning.

**Integration** — a complete REST surface over all of it, automated Obsidian
reporting, a dashboard covering every section, system-wide lineage
(`/lineage/*`), three-state health checks, shared-token authentication, and
production preflight validation.

**AI gateway** — every runtime AI call passes through one place that
classifies the task, rate-limits, deduplicates, checks a budget, routes to a
tier, and audits the result. Deterministic work uses no model at all;
high-volume language work prefers a local model; frontier reasoning is
reserved for thesis synthesis and contradiction resolution. See
[docs/ai-gateway.md](docs/ai-gateway.md).

### What is deliberately not implemented

**Broker execution.** Not "not yet" — structurally absent. No broker SDK is
imported anywhere in the tree, no route resembling order placement is
registered, and no signal category names an executable action. All three are
asserted by tests over the real source tree
(`tests/test_system_invariants.py`), not left to convention.

Paper trading is the only trading that exists here, and opening or closing
even a paper position requires explicit `confirm=true` — it never happens as
a side effect of anything else.

### AI is auxiliary, not load-bearing

The deterministic core — market data, quant, risk, backtesting, portfolio,
paper trading, the scheduler — runs unchanged with every AI provider
disabled, and a test asserts it. Machines calculate; models reason about
what was calculated. No `ai/` module can import a trading path, and every
`/ai` route is read-only.

Nothing calls a model automatically. The research queue fills itself
deterministically and shows, per entry, whether reasoning is judged worth
paying for — including the refusals, with reasons — but only a human ever
starts one.

### Honesty properties

The system is built to distinguish *not knowing* from *knowing zero*, and
that distinction survives all the way to the screen:

- A portfolio with one snapshot reports `daily_return: null`, never `0.0` —
  one data point is not a return.
- A position with no current price is excluded from market value rather than
  valued at cost.
- A trade with no stop has an undefined R-multiple, not a zero one.
- A signal with no evidence is not served at all (Rule 10).
- A lineage stage with no record says so, rather than inventing provenance.

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

Every item that used to be listed here (no real provider, no scheduled jobs,
no watchlist backend, no auth) has since been built. These are the ones that
remain — see [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)
for the full assessment and [docs/security.md](docs/security.md) for the
security-specific gaps.

- **No rate limiting.** A caller can trigger unbounded Anthropic spend via
  `POST /research/queue/{id}/process`. This is the most consequential gap.
- **Authentication is a single shared secret**, and opt-in: with
  `API_AUTH_TOKENS` empty the API is open. That is the right default for
  `localhost` and wrong anywhere else, so `/health` reports UNAVAILABLE when
  `APP_ENV=production` and no tokens are set.
- **Single-operator only.** No user accounts, no tenancy, no per-user audit.
- **No TLS in-app** — plaintext unless fronted by a reverse proxy.
- **No circuit breaker** on failing providers, and no request idempotency
  keys, so a client retry after a timeout could open a duplicate paper
  position.
- **No dependency vulnerability scanning** in CI.
- **No broker execution**, and none is planned. See the Critical Design
  Rules in [docs/architecture.md](docs/architecture.md).

## Future work

The 37 phases of the implementation plan are complete. Beyond them, in
rough order of value: a token-bucket rate limiter on the Claude-spending
routes, `pip-audit`/`npm audit` in CI, a circuit breaker for market data
providers, and request idempotency keys on the paper-trading endpoints.

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
