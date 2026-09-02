# Learning & Feedback Loop

`brain/learning/`. Measures what actually happened, then writes it down in
both stores — PostgreSQL so the numbers stay queryable and comparable,
Obsidian so the narrative sits beside the theses and trades it judges
(Rules 5/6).

## The honesty problem, and how each metric answers it

"Accuracy" is only meaningful where there was a falsifiable claim. This
module takes three explicit positions rather than producing a uniform
scoreboard:

### 1. Signals are scorable

`ACCUMULATE` / `REDUCE` / `EXIT_REVIEW` carry an implied direction, so a
forward return over a horizon (default 30 days) can confirm or refute them.

`WATCH` / `RESEARCH` / `THESIS_REVIEW` carry **no** directional claim and
are **excluded, not scored**. Grading them against a direction they never
stated would manufacture a failure rate out of nothing. The report names
the exclusions rather than hiding them.

- **False positive** = a directional signal contradicted by the outcome.
- **False negative** = an adverse move worse than −15% that **no**
  `REDUCE`/`EXIT_REVIEW` warned about.
- **Unresolved** = the horizon hasn't elapsed. Counted separately, never
  folded into the denominator — and `accuracy` returns `None`, not `0.0`,
  because "not known yet" must not read as "everything was wrong."

### 2. Research is *not* scorable — yet

A `ResearchAnalysis` contains no falsifiable directional prediction. So
forward returns after publication are reported as **outcome context** and
carry `is_accuracy_score: False` plus a written explanation. Inferring a
direction the research never claimed would be inventing the prediction we
then grade (Rule 4).

To make it measurable, add an explicit directional expectation to the
research schema — that's a deliberate future change, not an oversight.

### 3. Nothing claims significance a sample can't support

Every block carries its `sample_size`, and `is_significant` is `False`
below `MIN_SAMPLE_SIZE` (10 — reusing the Phase 11 journal threshold, so
"too small to trust" means the same thing everywhere). Warnings render
**inline with the number**, not in a footnote.

## Thesis accuracy

Counts current assessments (intact / strengthened / weakened / invalidated)
and computes **time to invalidation** from thesis creation to its *first*
invalidating review — a later re-review doesn't restart the clock.

This required a new `thesis_review_records` table, written by
`ThesisAgent.apply()`. The Obsidian note remains the narrative audit trail
(Rule 9); this table makes the same history *measurable* instead of
approximated from a single current-state field. With no invalidations,
median days reports `None` rather than a misleading `0`.

## Strategy performance

Closed trades grouped by market regime, sector, and market-cap bucket, with
win rate / expectancy / profit factor per group.

Trades with **no R-multiple** (no stop was ever defined) are counted and
**excluded** rather than scored with invented risk — consistent with the
Phase 20 journal rule.

## Reviews

`monthly` (job, every 30 days), `quarterly`, `annual` — same engine, and
`period_bounds()` always returns the *last completed* period. Reviews upsert
by `(kind, period_start)`, so regenerating refreshes rather than
accumulating duplicates.

```bash
python -m apps.worker.main run learning_review
```

Obsidian is optional: if no knowledge store is supplied, the PostgreSQL
record is still written, with `obsidian_note_path` left NULL.

## Testing

`tests/brain/learning/` — 29 tests, led by the honesty properties:
non-directional signals are excluded, unresolved outcomes yield `None` not
`0.0`, small samples are never significant, research outcomes assert
`is_accuracy_score is False`, stop-less trades are excluded and counted,
and an empty history produces an honest empty report rather than zeros
dressed as findings.
