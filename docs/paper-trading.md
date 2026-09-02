# Paper Trading

`paper_trading/`. The order layer on top of the Phase 16 accounting:
proposals, human approval, execution, snapshots, and journal integration.

## The approval gate

A signal can *suggest* a position change. Only a person can approve it.
Only an approved proposal can execute.

```text
signal -> proposal(pending_approval) -> approve() -> execute_proposal() -> transaction
                                     \-> reject() / expire()
```

`execute_proposal()` raises `ApprovalRequiredError` for **any** status other
than `approved` — pending, rejected, expired, or already-executed. The
approval step cannot be skipped by a job, an agent, or a caller that
forgot (Rule 7). Approving and executing are also deliberately **separate
calls**, so approval alone changes nothing.

Even after approval, execution writes rows in this database and nothing
else. There is no broker connectivity anywhere in TradingBrain (Rule 8).

## Signal → proposal mapping

| Signal | Proposal |
|---|---|
| `ACCUMULATE` | buy, 5% of initial equity (capped by cash) |
| `REDUCE` | sell 25% of the position |
| `EXIT_REVIEW` | sell the full position |
| `WATCH` / `RESEARCH` / `THESIS_REVIEW` | **nothing** |

The last row matters: those three are prompts to *look*, not to trade, so
they produce no proposal at all. Sell-side signals also propose nothing
when there's no position — there's nothing to trim.

Every proposal carries the originating `signal_id` and the signal's
reasoning in its rationale, so a proposal is traceable back to the evidence
that prompted it (Rule 10).

## Trade journal integration

Paper fills become `Trade` rows, so the Phase 11 Trade Journal Review Agent
analyses simulated trades with exactly the machinery it uses for any other
trade — one journal, one review path.

- A buy opens a trade record; **averaging in doesn't open a second one**
  (it's still one trade).
- A sell closes it only when the position goes flat; **a partial trim
  leaves the trade open**.
- `r_multiple` is computed **only when the trade recorded a stop**.
  Back-fitting one from the exit price would invent risk that was never
  defined, so it stays NULL — and the review agent already excludes
  trades without an R-multiple, so a missing stop quietly shrinks the
  sample instead of inflating it with fiction.

That required making `trades.stop_price` and `trades.risk_amount` nullable
(migration `d7f13c86b402`) — an honest schema change, since a paper
position genuinely may have no stop.

## Tracking

Exposure, allocation and returns are computable from current state. **Drawdown
is not** — it needs an equity history, which `paper_portfolio_snapshots`
provides. Snapshots are unique per `(portfolio, date)`, so re-running the
daily job updates rather than duplicates.

`performance()` returns total return, CAGR, Sharpe, volatility and max
drawdown over the snapshot series, reusing the existing `quant/` functions.
With fewer than two snapshots the ratios come back as `0.0` rather than as
invented figures.

Snapshots record `unpriced_positions`, and `PerformanceSummary.fully_priced`
surfaces it. A valuation taken while some holdings had no price is still
useful, but it must say so rather than implying completeness (Rule 4) — the
`portfolio_update` job returns `PARTIAL` in that case.

## Scheduled job

`portfolio_update` (daily 22:30 UTC, after prices land) — the last of the
two jobs deferred from Phase 15, registered now that its subject exists.

```bash
python -m apps.worker.main run portfolio_update
```

## Testing

`tests/paper_trading/` — led by the gate: an unapproved, rejected, expired
or already-executed proposal cannot execute, and approval alone doesn't
move a position. Then the signal→proposal mapping (including the three
categories that propose nothing), journal behaviour for averaging in,
partial exits and missing stops, and snapshot idempotency, drawdown, and
unpriced-position reporting.
