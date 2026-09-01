# TradingBrain Architecture

## Purpose

TradingBrain is a modular AI-assisted trading and investment intelligence
system. The initial phases build a research and reasoning foundation — not
an autonomous trading bot. Broker execution is explicitly out of scope until
the entire research, thesis, quantitative, risk, audit, and paper-trading
stack has been independently validated.

## Layer responsibilities

| Layer | Responsibility |
|---|---|
| Obsidian | Long-term knowledge / memory (notes, theses, reviews) |
| PostgreSQL | Structured financial data (prices, trades, metrics, signals) |
| Python (quant/) | Deterministic quantitative analysis |
| Claude (brain/, integrations/claude) | Reasoning / research layer |
| TradingBrain API (apps/api) | Orchestration layer |
| Broker execution | Disabled in this phase |

## Target end-state data flow

```text
                    MARKET DATA
                        |
                DATA INGESTION
                        |
                        v
                DATA NORMALIZATION
                        |
                        v
              POSTGRESQL / TIMESCALE
                        |
                        v
              QUANTITATIVE ENGINE
                        |
          +-------------+-------------+
          |             |             |
      Technical    Fundamental     Portfolio
      Analysis      Analysis        Analysis
          |             |             |
          +-------------+-------------+
                        |
                        v
                  CLAUDE REASONING
                        |
                        v
                OBSIDIAN KNOWLEDGE
                     GRAPH
                        |
                        v
                  THESIS ENGINE
                        |
                        v
                 DECISION ENGINE
                        |
                        v
                  RISK ENGINE
                        |
                        v
                 HUMAN APPROVAL
                        |
                        v
                 BROKER EXECUTION   <- not implemented; out of scope
```

The current implementation stops at:

```text
Claude Reasoning
        ↕
Obsidian Knowledge
        ↕
Quantitative/Data Layer
```

## Repository layout

```text
trading-brain/
├── apps/
│   ├── api/            FastAPI orchestration layer
│   ├── worker/         Background/scheduled jobs
│   └── dashboard/      Next.js/TypeScript UI (thin client over apps/api)
├── brain/
│   ├── market/          Market context assembly
│   ├── research/        Research agent
│   ├── thesis/          Thesis agent
│   └── review/          Trading journal review
├── quant/
│   ├── indicators/       Technical indicators (deterministic)
│   ├── fundamentals/     Fundamental analysis (deterministic)
│   ├── valuation/        Valuation models (deterministic)
│   └── performance/      Performance/risk statistics (deterministic)
├── data/
│   ├── ingestion/        Market data provider adapters
│   ├── normalization/    Raw -> normalized schema
│   └── storage/          Persistence helpers
├── integrations/
│   ├── obsidian/         KnowledgeStore abstraction + Obsidian implementation
│   └── claude/           LLMProvider abstraction + Claude implementation
├── models/               SQLAlchemy models + Pydantic schemas
├── config/               Settings, structured logging
├── tests/
├── scripts/
├── docs/
└── docker/
```

## Phase roadmap

0. **Architecture & repository foundation** — this document, monorepo
   layout, FastAPI/worker skeletons, Docker Compose, structured logging,
   settings. **Done.**
1. **Obsidian knowledge architecture** (vault spec, templates). **Done.**
2. **Obsidian MCP/REST integration** (`KnowledgeStore` abstraction). **Done.**
3. **PostgreSQL data layer** (schema, migrations). **Done.**
4. **Market data abstraction** (`MarketDataProvider`, mock provider first). **Done.**
5. **Quantitative engine** (technical, risk, performance — all deterministic,
   unit-tested). **Done.**
6. **Market regime engine** (descriptive, rule-based classification). **Done.**
7. **Claude research layer** (`LLMProvider` abstraction, Claude implementation). **Done.**
8. **Context assembler** (targeted retrieval across Obsidian + PostgreSQL +
   quant + regime — never the full vault). **Done.**
9. **Research agent.** **Done.**
10. **Thesis agent** (explicit `THESIS_INTACT` / `STRENGTHENED` / `WEAKENED` /
    `INVALIDATED` / `INSUFFICIENT_EVIDENCE` states; changes are auditable). **Done.**
11. **Trading journal intelligence.** **Done.**
12. **Remaining TradingBrain API endpoints.** **Done.**
13. **Dashboard foundation** (Next.js/TypeScript). **Done.**

All phases from the initial plan are complete. Phases were implemented
sequentially; each phase's tests, docs, and acceptance criteria were
finished before the next one started. See section 24 of the original
implementation prompt for the full acceptance checklist — every item is
satisfied except broker execution, which remains permanently out of scope
until the full research/thesis/quant/risk/audit/paper-trading stack is
independently validated (Rule 8).

## Critical design rules

1. Claude is a reasoning component, not a source of truth.
2. Financial calculations must be deterministic (`quant/`, never an LLM).
3. Market data must be explicitly sourced.
4. Never fabricate live financial data.
5. Obsidian is the knowledge layer.
6. PostgreSQL is the structured-data layer.
7. Claude does not directly execute trades.
8. No live broker integration in these phases.
9. Every investment thesis change must be auditable.
10. Every trade decision must eventually be traceable to evidence.
11. All AI outputs must include uncertainty/confidence where appropriate.
12. Never represent AI-generated analysis as guaranteed financial advice or
    guaranteed prediction.

## Phase 0 environment assessment

- Greenfield repository — the working directory was empty and not a Git
  repository prior to this phase.
- Local Python: 3.11.9. Docker images pin 3.12-slim for the preferred
  runtime; local dev works on 3.11+ (see README "Assumptions").
- Node 22.14.0 / npm 11.5.2 available for the future Next.js dashboard
  (Phase 12) — not used in this phase.
- Docker 28.3.2 / Compose v2.38.2 available.
- No existing functionality to preserve — nothing was overwritten.
