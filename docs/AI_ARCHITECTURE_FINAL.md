# AI Architecture — Final Assessment

Phases 38–46. Written to be useful rather than reassuring: the YELLOW rows
and the Known Limitations section are the point of the document, and no row
is GREEN because a test merely exists.

**Verified at:** commit `bea46c3`
**Verification:** 696 tests (116 of them AI-specific) · mypy clean over 164
source files · ruff clean · tsc clean · eslint clean · `next build` clean
across 18 routes · 52 API paths, 5 of them AI.

---

## 1. Current architecture

```
Application service          never constructs a provider client
        |
   AI Gateway                validate → classify → rate limit
        |                    → dedupe/cache → budget → route
        |                    → invoke → account → audit
        |
   Provider registry         local (OpenAI-compatible) | anthropic
        |
   Model                     per tier, from configuration
```

The order is chosen so the cheapest refusal comes first. A rate-limited
caller is rejected before a cache lookup; a cached answer returns before a
budget has to reason about a call that will not happen.

The deterministic core — market data, validation, quant, risk, backtesting,
portfolio, paper trading, scheduler — is upstream of all of this and runs
unchanged when every provider is disabled.

## 2. AI call inventory

The audit (Phase 38, `AI_CALL_MAP.md`) found the surface was **smaller than
expected**, which changed the plan: there was no sprawl to rein in, and the
work became about governing four call sites properly rather than
consolidating dozens.

| Call site | Task | Trigger | Tier |
|---|---|---|---|
| `POST /research/{ticker}` | Research synthesis | Human | Frontier |
| `POST /research/queue/{id}/process` | Research synthesis | Human | Frontier |
| `POST /thesis/{id}/review` | Thesis review | Human | Frontier-high |
| `POST /trades/journal/review` | Journal review | Human | Local |

Three findings worth recording:

- **No scheduled job invokes a model.** Verified by parsing imports across
  `apps/worker`, `data/ingestion`, `quant`, `backtesting`, and
  `paper_trading` — all clean. The nightly research refresh detects and
  scores changes deterministically.
- **Every call is human-initiated.** There are no automatic triggers, and
  the escalation layer added in Phase 42 deliberately preserves that.
- **`analyze()` and `summarize()` were dead surface** — only `extract()` was
  ever called in production. They remain on the interface because the
  gateway adapter implements all three, but nothing calls them.

## 3. Model routing policy

| Tier | Work | Enforcement |
|---|---|---|
| **0 — none** | Indicators, returns, volatility, risk, portfolio maths, backtests, ranking, filtering, validation, database queries | No model may be invoked |
| **1 — local** | Summarisation, classification, extraction, deduplication, note organisation, journal review | `AI_LOCAL_MODEL` |
| **2 — frontier** | Thesis synthesis, multi-source research, market interpretation | `AI_FRONTIER_MODEL` |
| **3 — frontier-high** | Thesis revision, contradiction resolution, high-impact conflicting evidence | `AI_FRONTIER_HIGH_MODEL` |

An unset tier is **unavailable and reported as such**. It is never
substituted from another tier: a silent upgrade is a silent bill, a silent
downgrade is a silent quality change (Rule 11).

Escalation rules, all inspectable at `GET /ai/routing`:

1. Contradictory evidence escalates research synthesis to high reasoning.
2. A high-risk task escalates off the local tier.
3. **A failure never escalates a tier** — that would turn an outage into an
   invoice.
4. A `local_only` request is never escalated; privacy outranks quality.

## 4. Event-driven escalation

`ai/escalation.py` answers *"would reasoning add anything?"* and defaults to
no.

Never escalating, at any magnitude: price shocks, large moves, stale
research, new candles, routine scheduled scans, marginal indicator changes.
These are facts the quant layer already reports; a model would restate them
more expensively.

Escalating above a materiality threshold: earnings releases, regime shifts,
thesis violations. Thesis violations use a lower threshold — missing one
costs more than paying for one.

The module **cannot call anything**. It imports no gateway and no provider,
asserted by parsing its imports, which is what makes it safe to run over
every detected change on every scan. Its verdicts — including refusals, with
reasons — surface on `GET /research/queue`, and listing that queue records
zero AI usage.

## 5. Cost model

Pricing is **configuration, not a constant** (`AI_MODEL_PRICING`, per-million
token rates as JSON). No prices are hard-coded, and no token or price values
were invented for `AI_COST_MODEL.md`.

With no price configured, cost reports **unknown — never zero** — and
`/ai/usage` states how many calls had unknown cost, so a low total is never
mistaken for a complete one.

Four independent controls:

1. Rate limits, per principal, applied before any expensive work.
2. Deduplication of in-flight requests and caching of completed ones.
3. Budgets per request / hour / day / month, warning at 80%, then blocking.
4. Bounded retries with a hard ceiling.

## 6. Provider architecture

Two providers behind one interface: a local OpenAI-compatible endpoint
(Ollama, LM Studio, vLLM, llama.cpp) and Anthropic. Adding a third requires
no change to any application service.

`anthropic` is importable from exactly two files. Every other module is
provider-independent, asserted by parsing the tree.

## 7. Security model

- External content is fenced as `UNTRUSTED DATA`; every system prompt states
  that instructions inside it must never be complied with.
- Prompts are never persisted — fingerprint and character count only.
- The principal is a truncated SHA-256 of the bearer token, never the token.
- Empty prompts, oversized prompts, unbounded output, and excessive retry
  counts are rejected at construction.
- No `ai/` module imports a trading path or broker SDK; every `/ai` route is
  GET-only. There is no `POST /ai/raw`.
- Cost is treated as an attack surface: a 200-request loop must not reach the
  provider more than five times, and a test asserts it.

## 8. Failure model

| Failure | Behaviour |
|---|---|
| No provider configured | 503 naming the missing setting; deterministic endpoints unaffected |
| Local provider down | Frontier fallback **only if policy permits** |
| Claude unavailable | Structured unavailable state — **never a fabricated result** |
| Timeout / provider 500 | Bounded retry within tier, then recorded failure |
| Auth failure / provider rate limit | Never retried |
| Budget exceeded | Blocked and audited |
| Database down | `/ai/status` still answers; it reads process state |

## 9. Observability

Five read-only endpoints (`/ai/status`, `/ai/usage`, `/ai/budget`,
`/ai/providers`, `/ai/routing`), rendered by the dashboard at `/ai`.

Each answers a question the brief asked: how many calls today, which models,
why Claude was used, what it cost, which task consumed most, how often local
handled it, how often escalation happened, how many were blocked, how many
failed.

When nothing has run, `/ai/usage` returns `recorded: false` with a reason
rather than a row of zeros — "no AI has run" and "AI ran and cost nothing"
are different facts.

## 10. Test results

| Suite | Result |
|---|---|
| Full suite | **696 passed** |
| AI-specific | 116 passed |
| mypy | Clean, 164 source files |
| ruff | Clean |
| tsc / eslint / next build | Clean, 18 routes |
| Migration↔model column check | `ai_requests`: 33/33 exact match |

Critical tests from the brief, all present and non-vacuous:

- **Cost boundary** — 200 requests, provider reached ≤5 times.
- **Budget alone** — same with rate limiting disabled.
- **Provider bypass** — parses the tree, with a guard that it sees >100 files.
- **Deterministic independence** — core runs with all providers disabled.
- **No execution** — real OpenAPI paths, with a guard that the scan sees >40.
- **AI cannot execute** — imports and route methods, with a scan guard.

Every scan-based test carries a non-vacuity assertion. That is a direct
response to a bug found in this repository: an execution-safety invariant
was iterating an empty list and passing while guaranteeing nothing.

## 11. Status table

| Component | Status |
|---|---|
| Deterministic-first architecture | **GREEN** |
| AI Gateway | **GREEN** |
| Local LLM | **YELLOW** |
| Anthropic integration | **GREEN** |
| Model routing | **GREEN** |
| Cost controls | **GREEN** |
| Rate limiting | **YELLOW** |
| Caching | **GREEN** |
| Observability | **GREEN** |
| Security | **GREEN** |
| Failure resilience | **GREEN** |
| Tests | **GREEN** |
| Production readiness | **YELLOW** |

Why the three that are not GREEN:

- **Local LLM — YELLOW.** The provider is implemented and unit-tested
  against a mock transport, but no local model has been run against it in
  this environment. The integration is correct by construction and unproven
  in practice.
- **Rate limiting — YELLOW.** AI-spending routes are limited and budgeted,
  which was the actual danger. Ordinary read endpoints remain unlimited.
- **Production readiness — YELLOW.** Unchanged from before this work, and
  for unchanged reasons: single shared secret, no multi-user support, no
  in-app TLS, no dependency scanning. The AI layer did not move this
  verdict, and claiming it did would be the kind of overstatement this
  document exists to avoid.

## 12. Known limitations

- **No local model has actually been run.** See above.
- **`analyze()` and `summarize()` are unused** in production.
- **The 10-migration chain was not re-verified against Postgres in this
  session** — Docker Desktop stopped partway through. The 9-migration chain
  was verified end to end earlier, and the new migration was checked
  column-by-column against its model (33/33). The chain is linear with a
  single head. This is a gap in verification, not a known defect.
- **Budgets are in-process for pre-flight**, durable only in `ai_requests`.
  Two processes would each enforce their own ceiling. `/ai/budget` reports
  both sources separately rather than reconciling them, because a
  discrepancy is itself information.
- **No batching.** The architecture supports asynchronous queuing, but no
  batch path is wired up: with four human-initiated call sites there is
  nothing to batch.
- **Prompt caching is not implemented**, only designed for. Static and
  dynamic context are separated in the evidence packet structure, which is
  the precondition, but no provider-side cache markers are set.

## 13. Remaining risks

| Risk | Severity | Mitigation in place |
|---|---|---|
| A future contributor calls a provider directly | Medium | Test fails the build |
| A prompt-injected document changes a routed task | Low | Task is set by the caller, not the content; tested |
| Unpriced model hides real spend | Low | Reported as unknown and counted; can be refused outright |
| Local model returns malformed structure | Medium | Schema-validated; failure is structured, not fabricated |
| Budget bypass across restarts | Low | Durable `ai_requests` record is authoritative |
| Cost estimate drifts from real billing | Medium | Estimates are labelled estimates; reconcile against provider invoices |

## Related

- [ai-gateway.md](ai-gateway.md) — operator guide
- [AI_CALL_MAP.md](AI_CALL_MAP.md) · [AI_COST_MODEL.md](AI_COST_MODEL.md) · [AI_ROUTING_POLICY.md](AI_ROUTING_POLICY.md)
- [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) · [security.md](security.md) · [resilience.md](resilience.md)
