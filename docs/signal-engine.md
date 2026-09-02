# Signal Engine

`brain/signals/`. Combines **market regime + quant metrics + research state
+ thesis state** into signals about where your *attention* should go.

## No execution categories — enforced three ways

```python
WATCH  RESEARCH  ACCUMULATE  REDUCE  EXIT_REVIEW  THESIS_REVIEW
```

There is no `BUY`, `SELL`, or `EXECUTE`, and that isn't left to discipline:

1. `SignalCategory` is a **closed enum** — the six above are all that exist.
2. `GeneratedSignal.__post_init__` **rejects** any category matching
   `FORBIDDEN_CATEGORIES` (`BUY`/`SELL`/`EXECUTE`/`ORDER`/`TRADE`/…), so
   even a future widening of the type can't smuggle one through.
3. No code path in the package reaches a broker (Rules 7/8).

The wording follows through: `EXIT_REVIEW` says *"review the exit decision —
this is not an instruction to sell."* `ACCUMULATE` says *"consider whether
adding fits your plan."* The human decides; the engine only points.

> Note the deliberate contrast with `backtesting/`, which *does* have
> `SignalAction.BUY/SELL`. Those are simulation instructions needed to
> measure a strategy — a different thing from telling a person to trade.

## Every signal carries evidence

A signal with no evidence **cannot be constructed** (`SignalError`), and the
repository refuses to store one. Rule 10: a signal must always be traceable
to what produced it.

Evidence is structured, and crucially it records three stances:

| Stance | Meaning |
|---|---|
| `SUPPORTS` | argued for the signal |
| `CONTRADICTS` | argued **against** it, recorded anyway |
| `UNKNOWN` | data we wanted but don't have |

Recording contradicting evidence is the point — *a signal that only lists
what supports it is advocacy, not analysis.* An `ACCUMULATE` on an extended
RSI says so, and its confidence drops accordingly.

## Confidence

```text
supporting / (supporting + contradicting + 0.5 × unknown)
```

Missing data counts at **half weight against** the signal. A number we
couldn't look up must never read as a passing grade (Rules 4/11) — so an
`ACCUMULATE` with no P/E on record still fires, but at reduced confidence
and with `"valuation could not be assessed"` recorded explicitly.

## Rules, most severe first

The engine emits **at most one signal per asset** — the first rule that
fires wins, so a broken thesis is never buried under a routine `WATCH`.

| # | Rule | Fires when |
|---|---|---|
| 1 | `THESIS_REVIEW` | thesis weakened/invalidated, or intact but unreviewed > 45d |
| 2 | `EXIT_REVIEW` | held **and** (thesis invalidated / ≥20% below cost / below 200-MA) |
| 3 | `REDUCE` | held, thesis intact, but RISK_OFF / bearish regime / negative momentum |
| 4 | `ACCUMULATE` | thesis intact **and** bullish regime **and** positive momentum **and** no valuation objection |
| 5 | `RESEARCH` | a research-queue entry scores ≥ 0.6 |
| 6 | `WATCH` | tracked (watchlist or held) with nothing more urgent |

Rule 4 is the spec's worked example, and all four conditions are required.
Rule 3 deliberately **defers** to rules 1–2: a broken thesis is a review
matter, not a trim.

An untracked, quiet asset produces **no signal at all**. Silence is a valid
answer — the engine doesn't manufacture attention.

## Deterministic

No Claude call participates in producing a signal (Rule 2). Claude's
research *output* is an input, but the combination logic is code — so the
same stored state always yields the same signals and confidences.

## Storage

Extends the existing `signals` table (Phase 3) rather than adding a
parallel one: new `category`, `confidence`, `reasoning`, `evidence`,
`status`, `acknowledged_at` columns. Lifecycle is `active` →
`acknowledged` | `dismissed`.

```python
from brain.signals import SignalEngine
result = SignalEngine().run(session)
result.by_category()   # {"ACCUMULATE": 3, "THESIS_REVIEW": 1, ...}
```

## Testing

`tests/brain/signals/` — 25 tests, led by the safety properties: the
category set contains no execution action, an execution-shaped signal
cannot be constructed, and an evidence-free signal can be neither built nor
stored. Then every rule (fires and defers), confidence arithmetic including
the unknown-data penalty, severity ordering, determinism, and the
acknowledge/dismiss lifecycle.
