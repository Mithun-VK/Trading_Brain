# AI Cost Model

How TradingBrain calculates what its AI usage costs, and what it can and
cannot currently say about that.

---

## What this model is built from

**Measured:** request shapes. The static per-call overhead figures below were
measured directly from the code, not estimated — they are the serialized
length of the system prompt plus the JSON Schema tool definition that is sent
on every call.

**Structural:** the amplification factors. These follow from the retry
configuration and the trigger inventory, both of which were read from source.

**Not measured, and deliberately not invented:** actual token counts and
actual spend.

> **The system has never recorded a single token.** `response.usage` is
> returned by the Anthropic SDK on every call and discarded on every call.
> There is no historical usage data to model from. Any "calls per day" or
> "cost per month" figure in this document would therefore be a number I made
> up, and Rule 4 of this project forbids exactly that.
>
> So this document defines the **model** — the arithmetic, the multipliers,
> and the configuration it reads — and the system fills in the values once
> `ai_requests` starts recording them. The dashboard's spend figures show
> "not recorded" until real usage exists, rather than a plausible-looking
> zero.

## Pricing is configuration, never code

No pricing exists in the repository, and hard-coding rates would bake in
values that go stale silently. Rates live in `config/ai_pricing.py` as
operator-supplied configuration:

```python
AI_MODEL_PRICING = {
    "<model-id>": ModelPricing(
        input_per_mtok=...,       # supplied by the operator
        output_per_mtok=...,
        cache_write_per_mtok=...,
        cache_read_per_mtok=...,
    ),
}
```

Any model with no configured price yields an **explicitly unknown** cost —
never zero. A missing price must not read as a free call.

## The cost formula

For one request:

```text
cost = (uncached_input_tokens / 1e6) * input_per_mtok
     + (cache_write_tokens    / 1e6) * cache_write_per_mtok
     + (cache_read_tokens     / 1e6) * cache_read_per_mtok
     + (output_tokens         / 1e6) * output_per_mtok
```

Cache reads and writes are separated because they are priced differently: a
cache write typically costs *more* than an uncached input token and a cache
read substantially less. Collapsing them would make caching look free, and
caching a rarely-reused prefix is a genuine way to lose money.

When any component's rate is unconfigured, the whole result is
`CostEstimate(known=False, reason=...)` — partial arithmetic over a missing
rate is worse than no arithmetic.

## Measured static overhead

Identical on every call of a given task, and currently re-sent and re-billed
every time:

| Task | Schema | System prompt | Static total |
|---|---|---|---|
| Research analysis | 644 chars | 186 chars | **~207 tokens/call** |
| Thesis review | 744 chars | 186 chars | **~232 tokens/call** |
| Journal review | 557 chars | 186 chars | **~185 tokens/call** |

These are the natural cache-prefix candidates: they never vary, they are sent
on every request, and they are exactly what prompt caching exists for.

They are also small. Caching them is worth doing — it is free once the
plumbing exists — but nobody should expect it to dominate the bill. The
larger and more variable part of the input is the assembled evidence context,
which is per-ticker and only worth caching within a burst of requests about
the same ticker.

## Amplification factors

These are the multipliers that turn one user action into more than one
billable call. All were verified against source.

| Source | Factor | Status |
|---|---|---|
| **Retry** | up to **3x** | Real. `stop_after_attempt(3)` on `ClaudeConnectionError` — into which `RateLimitError` is mapped, so throttled requests are retried |
| **Scheduler** | **1x** | No scheduled job invokes an LLM. Verified across all 8 registered jobs |
| **Failure loop** | **1x** | No recursive or self-triggering AI path exists. No agent calls another agent |
| **Fan-out** | **1x** | Each request produces exactly one LLM call. No per-item loops |
| **Duplicate requests** | **unbounded** | Nothing prevents the same research request being issued repeatedly. This is the real exposure |

**Worst case today** is therefore not a runaway loop — it is a human or
script calling `POST /research/queue/{id}/process` in a tight loop, each
call costing a full frontier request with 3x retry amplification, with no
rate limit and no budget to stop it.

That is the specific hole Phases 44–45 close, and it is why rate limiting
is listed ahead of caching in priority: caching saves a percentage, whereas
the missing rate limit is unbounded.

## What the model tracks once recording starts

Per request, persisted to `ai_requests`:

```text
calls, by task_type / provider / model / tier / day
input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
estimated_cost (or explicitly unknown)
retry_count          -- so amplification is observed, not assumed
cache_hit            -- so cache value is measured, not asserted
escalated + reason   -- so tier-3 spend is always explainable
blocked + reason     -- so refusals are visible, not silent
```

Aggregations exposed through `/ai/usage` and the dashboard:

```text
calls/day, calls/month
tokens/day, tokens/month
spend/day, spend/month, spend against budget
local vs frontier share
escalation rate
cache hit rate
top tasks by cost, top tasks by frequency
```

## Budget arithmetic

Budgets are evaluated **before** the call, against a projection:

```text
projected = current_period_spend + estimated_request_cost
```

The estimate uses the request's context size and `max_output_tokens` —
assuming maximum output, deliberately. Under-estimating and then discovering
you exceeded the budget after paying is not a budget.

When the request's cost cannot be estimated because a rate is unconfigured,
the policy decides explicitly. The default is to **allow but flag**, because
blocking every call under an unpriced model would make adding a new model
break the system; that default is configurable for operators who want the
opposite.

## What this model cannot tell you yet

Stated so no one mistakes the structure for the substance:

- Actual spend to date — nothing was recorded.
- Realistic calls/day — depends entirely on operator behaviour, and there
  is no history to project from.
- Real cache hit rates — no caching has run.
- Real token counts per task — the context is variable and has never been
  measured in flight.

After a week of recorded usage every one of these becomes answerable from
`/ai/usage`. Until then the dashboard shows them as **not recorded**, which
is the honest answer, and the same convention the rest of TradingBrain uses
for values it has not observed.
