# Scheduler & Ingestion Engine

`apps/worker/`. Turns TradingBrain from on-demand into continuous, without
adding a scheduling dependency (no APScheduler/Celery).

```text
apps/worker/
├── scheduler/
│   ├── schedule.py     Schedule.daily / .interval / .manual  (pure is_due)
│   └── scheduler.py    JobScheduler: register, due_jobs, run_job, run_due
├── jobs/
│   ├── base.py         Job / JobContext / JobResult / JobStatus / JobTrigger
│   ├── daily_market.py DailyMarketUpdateJob
│   └── company_update.py CompanyUpdateJob
└── main.py             CLI: list | run <job> | run-due | loop
```

## Why no scheduling library

`Schedule.is_due(now, last_success)` is a **pure function**. Tests assert
scheduling behaviour (missed days, same-day suppression, interval waits)
without sleeping, patching the clock, or running a broker. `JobContext.now`
is passed in for the same reason — a job never reads the wall clock itself.

## Durable scheduling

"When did this last succeed?" is answered from the **`job_runs` table**, not
in-process state. Consequences that matter:

- A restarted worker doesn't re-run a job it already completed today.
- A worker that was down for three days still runs the missed daily job
  once, rather than skipping the window.
- `FAILED` runs don't satisfy a schedule (the job stays due); `PARTIAL` runs
  do (the job completed and made progress — otherwise it would loop forever
  on one permanently-bad symbol).

Every attempt is recorded, so a job that succeeds on attempt 3 leaves a
full trail with per-attempt errors and durations.

## Idempotency

Every job is idempotent, and that property comes from the **repositories**
(upsert-by-natural-key), not from scheduler bookkeeping — so a manual
re-run is always safe. This is asserted directly:
`test_daily_update_is_idempotent` runs the job twice and requires the second
pass to insert zero rows.

`DailyMarketUpdateJob` fetches incrementally from the last stored bar, with
a 5-day overlap so late vendor corrections get picked up — the overlap is
free because the upsert dedupes it.

## Failure isolation

One bad symbol does not abort a market update. Per-symbol `ProviderError`s
are collected into `JobResult.detail["failures"]`, the job returns
`PARTIAL`, and every other symbol still updates. Unhandled exceptions are
caught by the scheduler and recorded — **a bad job can never kill the
worker loop**.

## Running

```bash
python -m apps.worker.main list          # jobs and their schedules
python -m apps.worker.main run daily_market_update   # manual trigger
python -m apps.worker.main run-due       # everything currently due
python -m apps.worker.main loop          # continuous polling (the Docker CMD)
```

## Registered jobs

| Job | Schedule | Does |
|---|---|---|
| `daily_market_update` | daily 22:00 UTC | Incremental price fetch → validate → upsert; re-classify market regime from a benchmark asset. |
| `company_update` | every 7 days | Refresh company profiles and TTM fundamental metrics. |

Regime classification is **skipped** (nothing stored) when there are fewer
than 200 closes — an UNKNOWN-everything observation would be noise, not
information.

## Not yet registered

`portfolio_update` and `research_refresh` land with the systems they
operate on (paper portfolios in Phase 16, the research queue in Phase 17).
They aren't stubbed here: a registered job that silently does nothing would
be worse than an absent one.
