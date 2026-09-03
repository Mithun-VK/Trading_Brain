# AI Routing Policy

Which class of work goes to which tier, and why. This is the policy the
`AIRouter` implements; it is written down separately so the routing code can
be checked against a stated intent rather than being its own justification.

---

## The principle

```text
Machines calculate.
Statistical models predict.
Local LLMs process high-volume language.
Claude performs high-value reasoning.
Risk controls constrain decisions.
Humans remain the final authority.
Learning evaluates outcomes.
```

A tier is chosen by **what the task is**, never by which model happens to be
configured. Routing must be explainable after the fact: every decision
records the tier, the model, and the reason.

---

## TIER 0 — no LLM

Anything with a correct answer that can be computed. Sending these to a
language model is not merely wasteful, it is *wrong*: a model that returns a
plausible Sharpe ratio is worse than one that returns none, because the
plausible number will be believed.

```text
indicators                  returns and volatility
risk metrics                portfolio valuation
position sizing             backtesting
statistical tests           signal rule evaluation
data validation             database queries
ranking and filtering       change detection and queue scoring
report rendering            deduplication by content hash
```

**Current state: already compliant.** The Phase 38 audit found no LLM call in
any of these paths. This tier is a guard against regression, and is enforced
by a test asserting that the deterministic packages import and run with every
provider disabled.

## TIER 1 — local LLM

High-volume language work where the input is bounded, the output is
structured, and being slightly less articulate costs nothing.

```text
summarization of a single document
classification and tagging
entity extraction
document normalization
news categorization
near-duplicate detection where hashing is insufficient
routine Obsidian organization
low-value research summarization
trade journal pattern review
```

The test for this tier: *would a careful but non-expert reader produce an
acceptable answer?* If yes, it is Tier 1.

**Privacy note.** Tier 1 is also where privacy-constrained work belongs. A
request marked `privacy_requirement=local_only` may never leave the machine,
and the router refuses rather than escalating — an escalation that violates a
privacy constraint to satisfy a quality preference is a bug, not a fallback.

## TIER 2 — frontier standard

Reasoning across multiple sources, where the value is in synthesis rather
than in fluency.

```text
research synthesis across several notes and events
material company developments
market interpretation requiring judgement
routine thesis assessment
```

## TIER 3 — frontier high-reasoning

Reserved, and always explained. Every Tier 3 route records
`reason_for_escalation`, so frontier spend is never anonymous.

```text
major thesis revision
high-impact conflicting evidence
contradiction resolution across sources
complex investment research
high-value research review
```

**Escalation is earned, not automatic.** Two rules matter more than the list:

1. **A failure never escalates a tier.** If a Tier 1 model errors, the
   response is to retry within the tier or fail — not to hand the same work
   to the most expensive model available. Failure-driven escalation converts
   an outage into a bill.
2. **Low confidence is a reason to escalate; a bad response is not.** A Tier
   1 model that returns a well-formed answer with low self-reported
   confidence is a legitimate escalation trigger. A Tier 1 model that returns
   malformed JSON is a validation failure, and escalating it just pays more
   for the same broken pipeline.

---

## Routing inputs

```text
task_type              what kind of work this is
importance             consequence of being wrong
complexity             estimated reasoning depth required
required_reasoning     does synthesis across sources matter
latency_requirement    interactive vs background
context_size           tokens of assembled evidence
privacy_requirement    may this leave the machine
budget                 remaining allowance for the period
local_model_available  is a local provider healthy right now
frontier_model_allowed does policy permit frontier for this task
```

## Decision order

Order matters, because each step can end the request more cheaply than the
next:

```text
1. Is this Tier 0?              -> no LLM at all. Stop.
2. Rate limit                   -> reject before any expensive work
3. Deduplicate / cache          -> reuse an in-flight or valid cached result
4. Budget check                 -> allow / degrade / block
5. Select tier from the task
6. Apply privacy constraints    -> may downgrade, never upgrade past them
7. Check provider health
8. Apply the fallback policy
9. Invoke, record, audit
```

Rate limiting sits at step 2 deliberately. A limiter that runs after context
assembly has already paid for the database work it was supposed to prevent.

## Fallback policy

Explicit, never silent. This mirrors the market-data rule that a synthetic
provider may be a deliberate primary but never an automatic fallback.

| Situation | Behaviour |
|---|---|
| Local unavailable, task is Tier 1, policy permits frontier | Escalate to Tier 2, **record the escalation and its reason** |
| Local unavailable, task is Tier 1, policy forbids frontier | Fail with a structured unavailable result |
| Local unavailable, `privacy_requirement=local_only` | Fail. Never escalate — the constraint outranks the output |
| Frontier unavailable, task is Tier 2 or 3 | Fail with a structured unavailable result. **Never** silently answer with a local model: a Tier 3 question answered at Tier 1 quality, unlabelled, is the most dangerous possible output |
| Any provider returns malformed output | Validation failure. Bounded retry within the same tier, then fail |
| Budget exceeded | Block. Never downgrade to a cheaper model to stay under budget without recording it |

**Failure is always a structured unavailable state, never invented text.**
Deterministic components continue regardless — AI availability may never
determine whether a risk constraint is enforced.

## Current call-site assignment

| Call site | Today | Policy | Change |
|---|---|---|---|
| `ResearchAgent.research` | frontier standard | TIER 2, escalate to 3 on contradictions | Escalation added |
| `ThesisAgent` review | frontier standard | **TIER 3** | Upgraded — most consequential output in the system |
| `TradeJournalReviewAgent` | frontier standard | **TIER 1** | Downgraded — bounded input, latency-tolerant |
| All quant / signals / backtest / ingestion | deterministic | TIER 0 | No change; now guarded by test |

Note that this is not a uniform cost reduction. Thesis review gets *more*
expensive per call, because it was under-provisioned: it was running on the
same standard model as journal review despite being the reasoning whose
errors matter most. Routing by task means some tasks route up.
