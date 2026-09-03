# The AI Gateway

Every runtime AI call in TradingBrain passes through one place. This
document is the operator's guide to it: how it decides, what it costs, what
stops it, and what happens when it breaks.

The governing principle, and the reason this layer exists at all:

> Machines calculate. Statistical models predict. Local LLMs process
> high-volume language. Claude performs high-value reasoning. Risk controls
> constrain decisions. Humans remain the final authority.

An LLM is an **auxiliary** subsystem here. The deterministic core — market
data, quant, risk, backtesting, portfolio, paper trading, the scheduler —
runs unchanged when every provider is switched off. That is enforced by
`tests/ai/test_deterministic_independence.py`, not merely intended.

---

## 1. The path a call takes

```
Application service  (never touches a provider SDK)
        |
   AI Gateway        validate → classify → rate limit → dedupe/cache
        |                     → budget → route → invoke → account → audit
        |
   Provider          local (OpenAI-compatible) | anthropic
        |
   Model             per tier, from configuration
```

Order matters, and it is chosen so the cheapest refusal comes first: a
rate-limited caller is rejected before a cache lookup, and a cached answer
is returned before a budget check has to reason about a call that will not
happen.

**Application code may not construct a provider client.** No service, router,
or job imports `anthropic` or instantiates `Anthropic()`. This is asserted by
`tests/ai/test_no_provider_bypass.py`, which parses the source tree — a
bypass would defeat rate limiting, budgets, and the audit trail in one step,
so it is checked structurally rather than trusted.

## 2. Routing

Routing is a function of the task, not a hard-coded model name at the call
site. `GET /ai/routing` returns the live policy so it can be checked against
[AI_ROUTING_POLICY.md](AI_ROUTING_POLICY.md) without reading source.

| Tier | Used for | Configured by |
|---|---|---|
| **TIER 0 — none** | Every calculation: indicators, returns, volatility, risk, portfolio maths, backtests, ranking, filtering, validation | *No model may be invoked* |
| **TIER 1 — local** | Summarisation, classification, extraction, deduplication, note organisation | `AI_LOCAL_MODEL` + `LOCAL_LLM_BASE_URL` |
| **TIER 2 — frontier** | Thesis synthesis, multi-source research, market interpretation | `AI_FRONTIER_MODEL` |
| **TIER 3 — frontier high** | Thesis revision, contradiction resolution, high-impact conflicting evidence | `AI_FRONTIER_HIGH_MODEL` |

An unset tier is **unavailable**, and the router says so. It never
substitutes a model from another tier, because a silent upgrade is a silent
bill and a silent downgrade is a silent quality change (Rule 11).

Three escalation rules, all visible at `/ai/routing`:

- Contradictory evidence escalates research synthesis to high reasoning.
- A high-risk task escalates off the local tier.
- **A failure never escalates a tier.** Retrying a failed local call on a
  frontier model turns an outage into an invoice.

A `local_only` request is never escalated at all: the privacy constraint
outranks output quality.

## 3. When a call happens at all

The gate is [`ai/escalation.py`](../ai/escalation.py), and its default answer
is no. It classifies deterministically-detected changes and recommends a
tier; it **cannot invoke anything** — it imports no gateway and no provider,
which is asserted by parsing its imports.

Never a reason to reason, whatever the magnitude:

- a new candle
- a price move or shock
- a routine scheduled job
- a marginal indicator change

These are facts the quant layer already reports. A model would restate them
more expensively.

Escalation-worthy, above a materiality threshold: earnings releases, regime
shifts, and thesis violations. Thesis violations use a lower threshold
because missing one costs more than paying for one.

The verdict — including the refusals, with reasons — appears on every entry
of `GET /research/queue`, so the person deciding whether to spend money sees
the recommendation before they click. **Listing the queue records zero AI
usage**; merely looking at the system never costs anything.

There are currently **no automatic AI triggers**. The research queue fills
itself deterministically and is only ever processed by an explicit human
action.

## 4. Context: evidence, not datasets

Models receive [evidence packets](../ai/evidence.py), never raw series. This
is partly cost — ten thousand candles is an expensive way to say "the trend
is up" — but mostly correctness: a model handed raw prices will compute, and
computed financial numbers must come from the quant layer (Rule 3).

Two invariants:

**Every item carries provenance.** An item without an origin cannot be
constructed, so `/lineage/*` can always corroborate what the model was told.

**Absence is explicit.** A missing input renders as
`- Earnings: NOT AVAILABLE (no fundamentals provider configured)` with an
instruction not to infer from it. A model shown *no* earnings section will
assume earnings were unremarkable; a model told the data was not retrieved
cannot. This is the same "null is not zero" rule the API and dashboard
already follow, carried into the prompt.

External documents are fenced as `UNTRUSTED DATA` describing what a document
says — never as instructions. The banner appears only when untrusted content
is present, because a banner on every packet is one nobody reads.

## 5. Cost controls

Four independent mechanisms, in the order they apply:

1. **Rate limits** — `AI_RATE_LIMIT_PER_MINUTE` (default 10),
   `AI_RATE_LIMIT_PER_HOUR` (default 100), keyed per principal. Applied
   *before* any expensive work.
2. **Deduplication and caching** — identical in-flight requests coalesce;
   completed identical requests are reused for `AI_CACHE_TTL_SECONDS`
   (default 900). Fingerprints are content-derived.
3. **Budgets** — `AI_BUDGET_PER_REQUEST`, `_PER_HOUR`, `_PER_DAY`,
   `_PER_MONTH`. Zero disables that window. At
   `AI_BUDGET_WARN_RATIO` (default 0.8) the gateway warns; past the limit it
   **blocks**, and the block is audited.
4. **Bounded retries** — capped, and a retry never escalates tier.

**Pricing is configuration, not a constant.** `AI_MODEL_PRICING` holds
per-million-token rates as JSON. With no price configured for a model, cost
reports as **unknown, never as zero** — and `/ai/usage` states how many calls
had unknown cost so a low total is never mistaken for a complete one. Set
`AI_ALLOW_UNPRICED_MODELS=false` to refuse unpriced models outright.

## 6. Failure behaviour

| Failure | Behaviour |
|---|---|
| No provider configured | `503` naming the missing setting. Deterministic endpoints unaffected |
| Local provider down | Frontier fallback **only if policy permits**; otherwise fail |
| Claude unavailable | Structured unavailable state. **Never a fabricated result** |
| Timeout | Bounded, recorded, surfaced |
| Budget exceeded | Blocked and audited |
| Database down | `/ai/status` still answers — it reads process state, not the database |

Nothing here substitutes invented text for a missing model answer. An
absent AI result is reported as absent, exactly like every other unknown in
this system.

## 7. Observability

`GET /ai/status` (process state, no database), `/ai/usage`, `/ai/budget`,
`/ai/providers`, `/ai/routing`. The dashboard renders these at `/ai`.

Every call writes an `ai_requests` row: request id, task, source, principal
fingerprint, routing decision and reason, escalation flag, tokens, estimated
cost, latency, success, block reason, cache hit.

**Prompts are not stored.** The row holds a `prompt_fingerprint` and a
character count, never the text — a table of prompts is a table of whatever
was in them. The principal is a truncated SHA-256 of the bearer token, never
the token itself: enough to tell two callers apart, useless if leaked.

These endpoints answer: how many calls today, which models, why Claude was
used, what it cost, which task consumed most, how often local handled it, how
often escalation happened, how many were blocked, how many failed.

## 8. Configuration

```bash
# Providers — an unset tier is unavailable, never substituted
LOCAL_LLM_BASE_URL=http://localhost:11434/v1   # Ollama, LM Studio, vLLM
AI_LOCAL_MODEL=llama3.1:8b
ANTHROPIC_API_KEY=sk-...
AI_FRONTIER_MODEL=claude-sonnet-5
AI_FRONTIER_HIGH_MODEL=claude-opus-5

# Cost — pricing is configuration; unset means "unknown", never zero
AI_MODEL_PRICING={"claude-sonnet-5":{"input":3.0,"output":15.0}}
AI_BUDGET_PER_DAY=5.00
AI_RATE_LIMIT_PER_MINUTE=10
AI_CACHE_TTL_SECONDS=900
```

With none of these set, `ai_enabled` is false: AI routes return 503 and
everything else works normally.

## 9. Troubleshooting

| Symptom | Cause |
|---|---|
| `503` from a research/thesis route | No provider configured. Check `/ai/status` |
| `429` | Rate limit. See `/ai/status` → `stats.blocked_rate_limit` |
| Blocked with a budget message | Past a ceiling. `/ai/budget` shows which window |
| Cost shows "unknown" | No `AI_MODEL_PRICING` entry for that model. Not a bug — an unpriced call is reported as unpriced |
| Repeated identical answers | Cache hit within TTL. Lower `AI_CACHE_TTL_SECONDS` |
| Tier reported unavailable | That tier's model variable is unset. It is never silently substituted |

## Related

- [AI_ROUTING_POLICY.md](AI_ROUTING_POLICY.md) — which tasks belong to which tier
- [AI_CALL_MAP.md](AI_CALL_MAP.md) — every AI call site
- [AI_COST_MODEL.md](AI_COST_MODEL.md) — volume and cost estimates
- [security.md](security.md) — prompt injection, secrets, untrusted content
- [resilience.md](resilience.md) — failure behaviour across the system
