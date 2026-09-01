# Trading Journal Intelligence

`brain/review/review_agent.py`. Pipeline: trades (PostgreSQL) → deterministic
performance statistics → Claude pattern review → Obsidian review note.

## Deterministic statistics first

`TradeJournalReviewAgent._group_stats()` computes win rate, profit factor,
expectancy, and average winner/loser using `quant/performance/stats.py` —
**before** Claude ever sees the data (Rule 2). Trades don't store a raw
dollar PnL, so R-multiple is used as the normalized PnL unit (standard
practice — it's comparable across trades with different position sizes).

Stats are computed overall and grouped by strategy and by market regime
(`Trade.market_regime`, captured at trade time).

## Sample-size honesty

Any group with fewer than `MIN_SAMPLE_SIZE` (10) trades gets a
`sample_size_warning` string instead of being presented as statistically
meaningful — both in the data structure and in the rendered Markdown (⚠
marker). This is a hard rule, not a suggestion to Claude: the warning is
computed deterministically and always shown regardless of what Claude says.

## Claude's role

Claude receives the deterministic stats (overall, by strategy, by regime)
plus a per-trade summary line, and is asked (via forced tool-use,
`PATTERN_REVIEW_SCHEMA`) to identify:

- `patterns` — e.g. "wins cluster in a specific regime"
- `repeated_mistakes`
- `rule_violations`
- `lessons`
- `confidence` (0-1, expected to be lower when the underlying sample is small)

Claude never recomputes win rate/expectancy/etc itself — it only reasons
over numbers the quant engine already produced.

## Output

`render_markdown()` produces a note for `09 Reviews/`, with a standing
disclaimer and the sample-size warnings inline. `publish()` writes it via
`KnowledgeStore`.

## Testing

`tests/brain/review/test_review_agent.py` — hand-computed reference values
for the grouped statistics (win rate, profit factor, expectancy), and
asserts open/unclosed trades are excluded from the sample.
