# Research Intelligence Engine

`brain/research/`. The piece that makes TradingBrain **continuous** rather
than on-demand: it decides *what deserves attention*, so you aren't relying
on remembering to ask.

```text
change_detection.py  deterministic rules  -> DetectedChange
priority.py          weighted scoring     -> ResearchPriority
intelligence.py      orchestration        -> research_queue rows
```

## Claude decides nothing here

Detection and scoring are **fully deterministic** (Rule 2). Claude is
invoked *afterwards*, by the Research Agent, to do the work on whatever
these rules surfaced. Keeping triage deterministic means the queue is
reproducible, explainable, and free of model-to-model drift.

## Change detection

| Change | Rule |
|---|---|
| `PRICE_SHOCK` | 1-day return ≥ `price_shock_pct` (default 5%) |
| `LARGE_MOVE` | return over `large_move_window` (20d) ≥ `large_move_pct` (15%) |
| `EARNINGS_RELEASE` | an `earnings` `market_event` within `earnings_lookback_days` |
| `THESIS_VIOLATION` | thesis `WEAKENED` (0.7) / `INVALIDATED` (1.0), **or** an intact thesis unreviewed for `thesis_stale_days` |
| `STALE_RESEARCH` | no research document within `stale_research_days` (never-researched counts) |
| `REGIME_CHANGE` | latest regime observation differs from the prior one |

Every threshold lives in `ChangeDetectionConfig` — nothing hard-coded.

**Magnitude normalization:** hitting a threshold exactly scores `0.5`;
twice the threshold saturates at `1.0`. This keeps magnitudes comparable
across rule types. Magnitude is *how hard the rule fired* — never a
probability or a forecast.

**Regime changes fan out only to assets you hold or watch.** Applying a
market-wide change to every known asset would bury genuine per-asset
signals under noise.

## Priority scoring

`score = Σ(weight × component) / Σ(weights)`, bounded 0..1.

| Component | Meaning |
|---|---|
| `importance` (0.40) | the change's magnitude |
| `novelty` (0.20) | days since last research; saturates at 60d |
| `portfolio_impact` (0.25) | largest share of any paper portfolio's initial equity |
| `watchlist_relevance` (0.15) | `0.6 + 0.2 × (extra lists)`, 0 if untracked |

Weights are `PriorityWeights` — configuration, not magic numbers buried in
code. Every `ResearchPriority` carries `reasons`, so a queue position is
always explainable rather than an opaque ranking.

`portfolio_impact` deliberately uses **cost basis, not market value**: this
is a triage signal about how much is at stake, and it must not silently
change depending on whether a current price happens to be available.

## The queue

Table `research_queue`, repository
`data/storage/research_queue_repository.py`. Worked **highest score first**
(ties broken by oldest detection).

Lifecycle: `pending` → `in_progress` → `done` | `dismissed`. A dismissal
takes a note, so choosing *not* to research something stays auditable
rather than silent.

**Enqueueing is idempotent** while an entry is still open: a repeat
detection for the same `(asset, change_type)` refreshes the existing row's
score instead of piling up duplicates. A closed (`done`/`dismissed`) entry
doesn't suppress a genuinely new detection later.

## Scheduled job

`research_refresh` (daily, 23:00 UTC — after the price update so it scores
against fresh data). This is the job deferred from Phase 15; it's
registered now that the queue it feeds exists.

```bash
python -m apps.worker.main run research_refresh
```

## Testing

`tests/brain/research/test_research_intelligence.py` — every detection rule
(fires and doesn't-fire cases), magnitude saturation, configurable
thresholds, each scoring component, queue ordering, idempotency, the
regime fan-out restriction, and the full queue lifecycle.
