# AI Call Map

A complete inventory of every place TradingBrain can invoke a language model,
produced by a fresh repository-wide audit rather than from prior phase
reports.

**Audited at:** commit `df22670` — Python, TypeScript, workers, migrations,
tests, and configuration.

---

## Summary of findings

| Finding | Detail |
|---|---|
| Production AI call sites | **3** — all `LLMProvider.extract()` |
| API endpoints that can invoke AI | **4** |
| Scheduled/background AI calls | **0** — no worker job invokes an LLM |
| Market-ingestion AI calls | **0** — ingestion is fully deterministic |
| Token usage captured | **None** — `response.usage` is never read anywhere |
| Cost accounting | **None** — no pricing model exists in the repository |
| Prompt caching | **None** — no `cache_control` anywhere |
| Rate limiting on AI routes | **None** |
| Budget enforcement | **None** |
| Dead interface surface | `analyze()` and `summarize()` are never called in production |

Two of these are worth stating plainly before the detail:

**The good news is structural.** No LLM call sits in the scheduler, in market
ingestion, in the quant engine, in the risk path, or in any loop. Every AI
call in this system is synchronous, user-initiated, and one-per-request. The
"scheduler amplification" and "failure-loop amplification" the phase brief
asks about **do not currently exist**, because there is no automated trigger
to amplify. That is a genuinely good starting position, and the refactor must
not regress it.

**The bad news is total blindness.** The system cannot answer "how much did
AI cost yesterday" at all — not approximately, not badly. `response.usage` is
returned by the Anthropic SDK on every call and discarded on every call.
There is no `ai_requests` table, no counter, no log field. The cost model in
[AI_COST_MODEL.md](AI_COST_MODEL.md) is therefore built from measured request
*shapes*, not from observed spend, and says so.

---

## Call site 1 — Research Agent

```text
call site            brain/research/research_agent.py:56
module               brain.research.research_agent.ResearchAgent.research()
method               LLMProvider.extract()
purpose              Extract structured research analysis (summary, positive
                     and negative factors, contradictions, risks, catalysts,
                     confidence) from an assembled evidence context
trigger              POST /research/{ticker}           user-initiated
                     POST /research/queue/{id}/process queue-driven, still an
                     explicit human action -- the queue never self-processes
frequency            On demand only. Zero automatic invocations.
input data           ContextBundle.to_prompt_context() -- a compact text block
                     of quant summary, market regime, active thesis, recent
                     trades, and Obsidian note paths with short snippets.
                     Deliberately NOT raw candles.
context size         Variable, dominated by note snippets. Static overhead
                     ~207 tokens/call (extract system prompt plus the
                     RESEARCH_ANALYSIS_SCHEMA tool definition), resent on
                     every call and never cached.
output size          max_tokens=2048
model                settings.anthropic_model (config, not hard-coded)
provider             Anthropic, via ClaudeProvider
sync/async           Synchronous -- blocks the HTTP request
retry behavior       3 attempts, exponential backoff 1s->10s, on
                     ClaudeConnectionError. RateLimitError is mapped into
                     that class, so a 429 is retried. Amplification 3x.
business value       HIGH -- genuine multi-source synthesis
deterministic replacement   No
local LLM sufficient        Partially. First-pass factor extraction from a
                     single document is a local-tier task; synthesis across
                     contradictory sources is not.
frontier required           Yes, for the synthesis step
routing tier         TIER 2, escalating to TIER 3 when contradictions present
```

## Call site 2 — Thesis Agent

```text
call site            brain/thesis/thesis_agent.py:54
module               brain.thesis.thesis_agent.ThesisAgent
method               LLMProvider.extract()
purpose              Re-assess an existing investment thesis against new
                     evidence; produce assessment, reasoning, supporting and
                     contradicting evidence, changed assumptions, and any
                     triggered invalidation conditions
trigger              POST /thesis/{ticker}/review      user-initiated
frequency            On demand only
input data           Evidence context plus the current thesis
context size         Static overhead ~232 tokens/call, uncached
output size          Bounded by max_tokens in the agent
model                settings.anthropic_model
provider             Anthropic, via ClaudeProvider
sync/async           Synchronous
retry behavior       3 attempts, exponential backoff. 3x amplification.
business value       HIGHEST -- a thesis change is the most consequential
                     reasoning output in the system, and it is auditable
deterministic replacement   No
local LLM sufficient        No
frontier required           Yes
routing tier         TIER 3 -- thesis revision is the canonical
                     high-reasoning task
```

## Call site 3 — Trade Journal Review Agent

```text
call site            brain/review/review_agent.py:70
module               brain.review.review_agent.TradeJournalReviewAgent
method               LLMProvider.extract()
purpose              Identify behavioural patterns, repeated mistakes, rule
                     violations, and lessons across journaled trades
trigger              POST /trades/{trade_id}/review    user-initiated
frequency            On demand only
input data           Journaled trade records and their notes
context size         Static overhead ~185 tokens/call, uncached
output size          Bounded by max_tokens in the agent
model                settings.anthropic_model
provider             Anthropic, via ClaudeProvider
sync/async           Synchronous
retry behavior       3 attempts, exponential backoff. 3x amplification.
business value       MEDIUM -- valuable, but tolerant of latency and of a
                     cheaper model
deterministic replacement   Partially. Counting rule violations and win/loss
                     streaks is arithmetic and belongs in the quant layer;
                     identifying behavioural patterns does not.
local LLM sufficient        Yes, for pattern extraction over a bounded set
                     of journal entries
frontier required           No
routing tier         TIER 1, escalating to TIER 2 only for a full periodic
                     review across many trades
```

## Non-call sites — verified clean

Checked specifically, because these are where AI cost usually hides.

| Location | Result |
|---|---|
| `apps/worker/jobs/*` (8 registered jobs) | **No LLM calls.** Only the report and learning jobs touch an integration at all, and only the Obsidian knowledge store |
| `apps/worker/jobs/research_refresh.py` | Deterministic — `ResearchIntelligenceEngine.scan()` does change detection and scoring with no LLM |
| `apps/worker/scheduler/*` | No LLM calls |
| `data/ingestion/*` | No LLM calls — market data is fully deterministic |
| `quant/*` | No LLM calls — all financial math is deterministic Python |
| `brain/signals/*` | No LLM calls — the signal engine is rule-based |
| `backtesting/*` | No LLM calls |
| `paper_trading/*` | No LLM calls |
| `brain/learning/metrics.py` | No LLM calls — metrics are computed |
| `brain/reporting/engine.py` | No LLM calls — reports are deterministic Markdown |
| `apps/dashboard/*` | No direct AI calls. The dashboard is a thin client; its only path to AI spend is reaching `POST /research/queue/{id}/process` |

## Provider instantiation — the bypass problem

```text
apps/api/dependencies.py::get_llm_provider()
  --> ClaudeProvider(settings)                integrations/claude/claude_provider.py:45
        --> anthropic.Anthropic(api_key=...)   <-- raw SDK, no gateway
```

Every AI-capable router receives its provider through
`Depends(get_llm_provider)`. There is exactly one construction path, which is
good — but it constructs a *provider*, not a *gateway*, so there is nowhere
for routing, budgets, caching, deduplication, or usage accounting to live.
This is the highest-leverage change in Phases 39–41.

## Retry amplification detail

`ClaudeProvider._request` retries on `ClaudeConnectionError`, and
`claude_provider.py:94` maps **both** `APIConnectionError` and
`RateLimitError` into that class. So a rate-limited request is retried three
times with backoff.

That is bounded, and not a retry storm — but it is the wrong classification.
A 429 means "you are asking too fast"; retrying it three times is a mild
version of exactly the wrong response, and it inflates cost on the very
requests the provider is already throttling. Rate limiting deserves its own
error class and its own policy, which Phase 40 introduces.

## Task classification for routing

| Task | Current | Should be | Reason |
|---|---|---|---|
| Indicator / return / volatility / risk math | deterministic | TIER 0 | Verified clean, no change |
| Change detection and queue scoring | deterministic | TIER 0 | Verified clean, no change |
| Report rendering | deterministic | TIER 0 | Verified clean, no change |
| Journal pattern review | TIER 2 (Claude) | **TIER 1 (local)** | Bounded input, latency-tolerant, no cross-source synthesis |
| Single-document summarization | not implemented | TIER 1 | Local-first if added |
| Research synthesis | TIER 2 | TIER 2 | Correct as-is |
| Research synthesis with contradictions | TIER 2 | **TIER 3** | Contradiction resolution is the high-reasoning case |
| Thesis review | TIER 2 | **TIER 3** | Highest-consequence output in the system |

The headline: **one of three production call sites is over-provisioned**
(journal review), one is correctly provisioned (research), and one is
*under*-provisioned — thesis review runs on the same standard model as
everything else, despite being the most consequential thing the system says.

Cost reduction here does not come from moving work off Claude in bulk; there
is very little bulk. It comes from prompt caching, deduplication, and not
paying frontier prices for the journal reviewer.
