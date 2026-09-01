# Development

## Backend (Python)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

pip install -e ".[dev]"
cp .env.example .env          # then fill in real values

pytest                        # full test suite
ruff check .                  # lint
mypy apps brain quant data integrations models config scripts   # type check
```

No live PostgreSQL, Obsidian instance, or Anthropic API key is required for
the test suite — every integration has a mock/fake counterpart (see each
`docs/*.md` file's Testing section).

## Frontend (dashboard)

```bash
cd apps/dashboard
npm install
cp .env.local.example .env.local   # points NEXT_PUBLIC_API_BASE_URL at the API

npm run dev      # http://localhost:3000, expects the API on :8000
npm run build    # production build + typecheck
npm run lint
```

The dashboard is a thin client over the API — it holds no business logic
and no direct database/Obsidian/Claude access. Every page degrades
gracefully (an `ErrorBox`, not a crash) when the API is unreachable or a
resource doesn't exist yet.

## Running everything together

```bash
docker compose up -d          # Postgres, Redis, API, worker
alembic upgrade head
cd apps/dashboard && npm run dev
```

## Adding a phase-consistent change

- New deterministic calculation → `quant/`, with a hand-verified
  reference-value test (see `docs/quant-engine.md`).
- New Claude-backed capability → an `LLMProvider.extract()` call against a
  JSON Schema, not free text you parse yourself (see `docs/claude.md`,
  `docs/research-agents.md`).
- New table → a SQLAlchemy model in `models/` + an Alembic migration (see
  `docs/database.md`).
- New API endpoint → a router under `apps/api/routers/`, dependencies from
  `apps/api/dependencies.py`, tests overriding those dependencies with
  fakes (see `docs/api.md`).
- Never add a route under `/orders`, `/execute`, `/buy`, `/sell` — the
  middleware guard in `apps/api/main.py` blocks them outright (Rule 8).
