# Failure Resilience

What happens when things break. As with [security.md](security.md), this
records what exists and names what does not.

The organising principle: **every external dependency is assumed to be
unavailable at some point, and none of them is allowed to take the system
down or to produce a silently wrong number.**

---

## 1. Outbound HTTP (market data, Obsidian, Claude)

| Concern | Where | Behaviour |
|---|---|---|
| Timeout | `data/ingestion/http_client.py`, provider constructors | Default 10 s, configurable via `MARKET_DATA_TIMEOUT_SECONDS` |
| Retry | `http_client.py`, `claude_provider.py`, `obsidian_knowledge_store.py` | tenacity, `stop_after_attempt(3)` |
| Backoff | same | `wait_exponential` — 0.5 s→4 s for providers, 1 s→10 s for Claude |
| Error classification | `data/ingestion/errors.py` | Transient (`ProviderUnavailableError`, `ProviderRateLimitError`) vs permanent (`ProviderAuthError`) — **only transient errors are retried** |

Retrying an auth failure three times is pointless and looks like an attack
to the provider, which is why the error taxonomy exists and the retry
predicate keys off it rather than off status codes at the call site.

**The health probe deliberately bypasses this.** `check_obsidian` issues a
single-shot 2 s `httpx.get` rather than going through the knowledge store,
because a health check that retries with backoff takes 15 s to tell you
something is down.

## 2. Provider fallback

`ProviderRegistry` tries `MARKET_DATA_FALLBACKS` in order when the primary
fails. One rule is enforced structurally rather than by convention:

```
set_fallbacks() rejects synthetic providers
```

A generated price silently substituted for a real one is worse than no
price, because every number downstream inherits the fabrication without
carrying any marker of it (Rule 4). A synthetic provider can be the
*primary* — that is a deliberate local-development choice — but it can never
be the thing you fall back into by accident.

## 3. Missing data is represented, not filled in

The system's most common "failure" is not an exception but an absence, and
it is handled by type rather than by exception:

- A position with no current price is `unpriced: true` and **excluded** from
  market value rather than valued at cost.
- A portfolio with one snapshot reports `daily_return: null`, not `0.0`.
- A trade with no stop has `r_multiple: null` — undefined, not zero.
- A signal with no evidence is not served at all (`SignalOut` is skipped
  from listings; fetching it by id is a 500 that names Rule 10).
- A lineage stage with no record is `recorded: false` with explanatory text.

The dashboard renders each of these as a distinct visible state
(`components/Value.tsx`), so the absence survives all the way to the reader.

## 4. The worker

- **A job never kills the worker.** `run_job` catches every exception, and
  records the failure as a `job_runs` row.
- **Every attempt is recorded**, so a job that succeeds on attempt 3 is
  distinguishable from one that succeeded first time.
- **Restart safety comes from the database, not memory.** `due_jobs` asks
  `get_last_successful_run`, so restarting the worker neither re-runs a
  completed daily job nor skips a missed one.
- **Failure does not consume the schedule slot.** Due-ness keys off the last
  *successful* run, so a failed job stays due.
- **Jobs are idempotent** by construction: the repositories upsert by
  natural key, so a manual re-run over the same window is always safe. This
  is a property of the repositories, not of scheduler bookkeeping.

> **Fixed in Phase 31.** A job that died on a rejected flush left the
> SQLAlchemy session in a failed transaction. Writing the `job_runs` row then
> raised `PendingRollbackError` from *outside* the `try` block — killing the
> worker and losing the failure record, at exactly the moment the record
> mattered most. The runner now rolls back before recording. Note that a
> failed *SELECT* does not poison a session; only a failed flush does, which
> is why the first version of the regression test passed against the bug.

## 5. The API

- A database outage returns **503 in health shape**, never a 500
  (`SQLAlchemyError` handler in `apps/api/main.py`).
- `/health` distinguishes `healthy` / `degraded` / `unavailable`, and
  aggregates by **worst-wins** — averaging health would hide the one broken
  thing.
- Health checks never raise; each catches broadly and reports the exception
  *type name only*, never its message, which could carry a connection
  string.
- Paper trade open and close both require `confirm=true`, so a retried or
  replayed request cannot open a position as a side effect.

## 6. Known gaps

| Gap | Consequence |
|---|---|
| **No circuit breaker** | A provider that is down stays in the rotation and every call pays the full retry cost (3 attempts × backoff) before failing over |
| **No request-level idempotency keys** | `POST /paper-trades` retried by a client after a timeout would open a second position. The `confirm` flag prevents accidental opens, not duplicate ones |
| **No dead-letter queue** | A job that fails every attempt is recorded and then simply retried on its next schedule; there is no quarantine or escalation |
| **No bulkheads between jobs** | Jobs share one session and run sequentially; a slow job delays the ones behind it |
| **No inbound rate limiting** | See [security.md](security.md) |

None of these is load-bearing for a single-operator system, which is why
they are gaps rather than bugs — but they would each need addressing before
this ran unattended for anyone else.
