# V4 — Regime Decomposition Report

**Strategy:** MA 20/50, frozen at `25f6746` (`v1.0-experiment-freeze`)
**Data:** Yahoo, 29,487 daily bars, 10 tickers + SPY, 2016-01-04 → 2026-09-01
**Trades analysed:** 268 closed round trips
**Status:** diagnostic only — no parameter was tuned and no strategy changed

---

## Verdict

**No coherent regime mechanism was found.** On the evidence below, MA 20/50
does not have a demonstrated edge that survives inspection, and I would not
proceed to V5 without either a different hypothesis or a materially larger
sample.

That is a finding, not a failure of the analysis. It is also the outcome the
phase brief anticipated: *"If it doesn't, we seriously consider discarding
the MA-cross strategy before spending more engineering effort on it."*

---

## The ten questions

### 1. Which regimes generate positive expectancy?

Pooled across all periods, **every regime is positive**:

| Regime | Trades | Expectancy | Total P&L | Profit factor | Significant? |
|---|---|---|---|---|---|
| crisis | 36 | +7.93% | +30,602 | 5.68 | yes |
| recovery | 37 | +4.52% | +15,967 | 3.04 | yes |
| bull | 132 | +3.11% | +31,559 | 2.30 | yes |
| sideways | 46 | +3.05% | +10,158 | 1.78 | yes |
| unknown | 17 | +17.40% | +20,568 | 9.96 | **no** |

### 2. Which regimes generate negative expectancy?

**None, when pooled** — and that is itself the problem. Pooling hides the
validation failure entirely. Per period:

| Regime | Train | Validation | Test |
|---|---|---|---|
| bull | +16,534 | **+5,455** | +9,570 |
| crisis | +21,940 | **−3,341** | +12,003 |
| sideways | +5,372 | **−4,104** | +8,890 |
| recovery | +9,385 | **−4,476** | +11,058 |

In validation, **three of four regimes lost money**. The same regimes were
profitable either side of it.

### 3. Does the strategy fail primarily in sideways markets?

**No — and this is the most damaging finding.**

- Sideways expectancy: **+3.05%**
- Trending (bull/bear) expectancy: **+3.11%**
- Difference: **−0.06% per trade**, far below a 1% materiality floor

A moving-average cross is *supposed* to whipsaw in range-bound markets.
That is its known failure mode and would have been a coherent mechanism.
**It is not visible in this data.** The strategy performs indistinguishably
in trending and ranging markets, which means whatever drives its results is
not the mechanism the strategy is built on.

### 4. Does volatility materially affect performance?

**No.** Low-vol +4.07% (214 trades) vs high-vol +3.60% (37 trades) — a
0.47pp gap, not material.

### 5. Does performance change after regime transitions?

| Group | Trades | Mean return | Win rate |
|---|---|---|---|
| Regime changed during trade | 155 | +6.59% | 49% |
| Regime unchanged | 113 | +2.46% | 41% |

Trades spanning a transition did better. With an 87-day average hold this
most likely reflects *duration* — longer trades span more transitions and
also capture more trend — rather than transitions conferring an edge.

### 6. Is the edge consistent across tickers?

**Broad in direction, narrow in magnitude.**

9 of 10 tickers profitable, but:

| Ticker | Total P&L | Avg return | Share of total |
|---|---|---|---|
| **NVDA** | **+48,777** | +22.04% | **45%** |
| GOOGL | +14,405 | +7.37% | 13% |
| AAPL | +14,120 | +5.66% | 13% |
| MSFT | +11,794 | +5.53% | 11% |
| AMZN | +10,131 | +5.32% | 9% |
| JPM | +4,603 | +2.98% | 4% |
| WMT | +3,667 | +2.01% | 3% |
| PG | +1,277 | +0.38% | 1% |
| JNJ | +1,123 | +0.89% | 1% |
| XOM | −1,044 | −0.74% | −1% |

**NVDA alone supplied 45% of all profit.** Strip it out and the remaining
nine names produce roughly 60,000 over 243 trades — a much more ordinary
result. This looks less like a trend-following edge and more like *having
held NVDA during 2016–2026*.

### 7. Is the apparent edge concentrated in only a few trades?

| Measure | Value |
|---|---|
| Top 1 trade | 16% of total P&L |
| Top 5 trades | 42% |
| Top 10 trades | **62%** |
| Winners / losers | 122 / 146 |

**The strategy loses more often than it wins** (46% win rate) and is
profitable only through asymmetry — a handful of large winners. Ten trades
out of 268 carry nearly two-thirds of the result.

That is not disqualifying on its own; trend-following is supposed to look
like this. But combined with findings 3 and 6, the asymmetry appears to come
from holding a few large winners rather than from the crossover signal.

### 8. Does the strategy outperform SPY risk-adjusted?

| Period | Strategy Sharpe | SPY Sharpe | Strategy MaxDD | SPY MaxDD | Avg exposure |
|---|---|---|---|---|---|
| train | 1.36 | 0.75 | −10.04% | −34.10% | 43.6% |
| validation | **−0.39** | 0.19 | −12.54% | −25.36% | 33.5% |
| test | 1.53 | 1.34 | −6.31% | −19.00% | 40.8% |

Risk-adjusted, the strategy beats SPY in 2 of 3 periods with about a third
of the drawdown — the one genuinely favourable finding. But it holds ~40%
average exposure, so on raw CAGR it loses in all three (10.41% vs 20.98% in
test).

*Per-regime SPY Sharpe is not computed: a buy-and-hold benchmark has no
trades to attribute to regimes, and inventing that comparison would be
worse than omitting it.*

### 9. Is the validation failure explained by regime composition?

**Only partially, and the residual is the concerning part.**

| Regime | Validation share | Elsewhere | |
|---|---|---|---|
| crisis | **31%** | 9% | ← over-represented 3.4× |
| bull | 36% | 43% | |
| recovery | 16% | 14% | |
| sideways | 17% | 26% | |

Crisis days were 3.4× more common in validation. But crisis is **+7.93%
pooled** and **−4.07% in validation**. So the strategy did not merely
encounter a hostile regime more often — **it behaved differently within the
same regime**. Composition alone does not account for the failure.

### 10. Is there enough evidence to justify continuing with MA 20/50?

**On this evidence, no.**

Against continuing:
- The expected mechanism (edge in trends, weakness in ranges) is **absent**
- 45% of profit from **one ticker**
- 62% of profit from **ten trades** out of 268
- A **negative validation period** not explained by regime composition
- Below-50% win rate with no compensating structural explanation

For continuing:
- Sharpe beats SPY in 2 of 3 periods at a third of the drawdown
- 268 trades is a usable sample
- 9 of 10 tickers directionally positive

The favourable points are real but thin, and every one of them is
consistent with "held large-cap US equities through a bull decade at 40%
exposure" rather than with a working crossover signal.

---

## What I would do next

**Not** parameter search across 10/30, 20/100, 50/100, 50/200. With no
mechanism identified, a parameter sweep would find whichever pair best fits
2016–2026 and manufacture exactly the overfit V4 exists to prevent. The V5
brief is right that a *stable region* beats a peak — but that test is only
informative once there is a mechanism to be stable about.

Three options, in the order I would rank them:

1. **Test the mechanism directly.** Compare against a random-entry control
   holding the same names for the same average duration at the same
   exposure. If MA 20/50 does not beat random entry, the signal contributes
   nothing and the result is the universe. This is one experiment and it is
   decisive.
2. **Re-run excluding NVDA**, and separately on an equal-weight basis, to
   see whether anything survives without the single dominant name.
3. **Widen the universe** beyond 10 US mega-caps. The current universe is
   survivorship-biased by construction — these are names that are large
   *today* — which the dataset audit already flags and which alone could
   account for the aggregate positive result.

Only if (1) shows the signal beats random entry does V5 robustness testing
become worth the engineering effort.

---

## Reproducing

```bash
python -m experiments.v2_baseline   # the frozen baseline
python -m experiments.v4_regime     # this decomposition
```

Raw output: `experiments/results_v4_regime.json` (per-trade records with
regime, MAE/MFE, and excursion data).

## Method notes

- Regime labels come from a **causal forward pass**; a label at bar *t* uses
  only bars ≤ *t*. Tested by truncation: labelling 300 bars gives identical
  answers for the first 250 as labelling 250 does.
- A date with no bar resolves to the most recent **earlier** label, never a
  later one.
- MAE/MFE use bar highs and lows, not closes.
- Crisis and recovery **override** trend labels — a "bull" label during a
  25% drawdown is technically defensible and practically useless.
- The 17 `unknown`-regime trades are the detector's 200-bar warm-up at the
  start of train. They carry a 17.4% expectancy on a 17-trade sample and are
  reported separately rather than pooled into a trend label.
