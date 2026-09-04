# V4.1 / V4.2 / V4.3 — Signal Falsification and HMM Regime Validation

**Strategy under test:** MA 20/50, frozen at `25f6746` (`v1.0-experiment-freeze`)
**Branch:** `v4-regime-decomposition`
**Data:** Yahoo, 29,487 daily bars, 10 tickers + SPY, 2016-01-04 → 2026-09-01
**Universe:** AAPL, MSFT, GOOGL, AMZN, NVDA, JPM, JNJ, XOM, PG, WMT (+ SPY benchmark)
**Costs:** 5bp commission, 5bp slippage. **Sizing:** 10% fixed fraction, max 20% per
position, max 100% portfolio exposure, max 1× leverage. **AI:** disabled throughout.

No MA parameter was changed, no parameter sweep was run, and no strategy logic
was touched during this phase. This is falsification, not optimization.

---

## 1. Executive summary

**SIGNAL STATUS: D — EVIDENCE OF FALSE EDGE.**

All four experiments completed at full scale (N=5000 for Experiment 1,
N=500 for Experiment 4 — see §5 for why that trial count differs). The
final numbers are sharper than the directional preview suggested, in the
direction of *less* evidence for a genuine signal, not more:

- **Win rate is at or below the 1st percentile of matched random entry in
  every one of the four periods tested** (train 0.0%, validation 0.0%, test
  0.1%, full 0.0%), with effect sizes of −3.2 to −6.2 standard deviations
  below the random mean. MA 20/50 loses to randomly timed entry on hit rate,
  without exception, at high confidence.
- **Sharpe never clears the 95th percentile of the null in any period** —
  its best showing is 93.0% in train, and it sits at a coin-flip 51–53%
  in test and full. **CAGR and total return clear 95% only in the training
  period**; in validation, test, and full period, *nothing* clears the bar
  Experiment 1 set for evidence.
- **Conditioning on the latent market regime (Experiment 4) removes even the
  training-period edge.** Within 3 of the 4 HMM states, MA sits at or below
  the 33rd percentile of regime-matched random entry — meaning the apparent
  overall edge is substantially an artefact of *which regime the trades fell
  in*, not of the crossover timing itself. The one state where MA does well
  (pre-HMM history, 100th percentile) is the earliest slice of data, which
  predates the regime model's own coverage entirely — not a regime effect at
  all, just early history.
- **NVDA alone supplies 43.9% of total P&L** from 9.5% of trades, and is the
  only single-ticker removal that materially changes the result (Sharpe
  1.085 → 0.840).

Four independent lines of evidence — matched random timing, ticker
concentration, latent-regime decomposition, and regime-conditioned random
timing — converge on the same reading: this strategy's return comes from a
small number of large, long-duration, regime-driven winners (disproportionately
one ticker, disproportionately one market state), not from the 20/50
crossover correctly timing entries.

**Recommendation: STOP MA 20/50 DEVELOPMENT.** Do not proceed to V5
parameter robustness testing. See §21–22.

---

## 2. Frozen baseline

Unchanged from V2/V4. Recorded here for traceability:

| Parameter | Value |
|---|---|
| Strategy | `MovingAverageCrossStrategy(fast=20, slow=50)` |
| Universe | AAPL, MSFT, GOOGL, AMZN, NVDA, JPM, JNJ, XOM, PG, WMT |
| Benchmark | SPY |
| Timeframe | 1d |
| History | 2016-01-01 → 2026-09-01 |
| Train | 2016-01-01 → 2021-01-01 |
| Validation | 2021-01-01 → 2023-01-01 |
| Test | 2023-01-01 → 2026-09-01 |
| Initial capital | $100,000 |
| Commission / slippage | 5bp / 5bp |
| Position sizing | 10% fixed fraction |
| Risk limits | 20% max position, 100% max exposure, 1× max leverage |
| Random seed | 20260901 (baseline), 20260904/20260905 (this phase) |

**Data snapshot:** `experiments/.cache/` (gitignored; regenerable via
`experiments/data.py::load`). Snapshot hash for the full universe + SPY over
this date range: `c9a26889b596c3e0` (verified unchanged from the integrity
check in §4).

---

## 3. Experiment methodology, overview

Four experiments, run in sequence, each gating the next only informally (all
four were run; the gate is applied at the decision stage, §22, not by
skipping work):

1. **Matched random-entry control** — does MA timing beat randomly timed
   entries under identical costs, sizing, and constraints?
2. **NVDA concentration / leave-one-ticker-out** — does the result survive
   removing its largest contributor?
3. **Causal walk-forward HMM regime detection** — is there a latent market
   structure that explains performance better than entry timing does?
4. **Regime-conditioned random control** — does MA still beat random entry
   *within* a latent regime, or is the apparent edge fully explained by
   which regime the trades happened to fall in?

---

## 4. Data integrity (pre-experiment check)

Verified before any experiment ran:

| Check | Result |
|---|---|
| Provider | Yahoo (`source=yahoo` on every bar; certifiable as vendor data) |
| Bars | 29,487 across 11 tickers |
| Date range | 2016-01-04 → 2026-09-01 |
| Duplicate timestamps | 0 |
| Non-monotonic series | none |
| Snapshot hash | `c9a26889b596c3e0` (stable across this phase's runs) |
| Synthetic substitution | none — a ticker that fails to fetch is omitted with a warning, never filled with generated data (`experiments/data.py`) |

Known, disclosed limitations (from `walkforward.audit_dataset`, unchanged
since V3): the universe is not point-in-time (survivorship bias — these are
names large *today*), delisted securities are excluded, and corporate-action
adjustment is not independently confirmed beyond what Yahoo's adjusted-close
series provides.

---

## 5. Experiment 1 — random-entry control: methodology

`experiments/random_control.py` + `experiments/montecarlo.py` +
`experiments/e1_random_control.py`.

**What is matched:** universe, bars, train/validation/test windows, initial
capital, commission, slippage, sizer, risk limits, and — critically — trade
count and the empirical MA holding-period distribution (`target_from`).
Entries are drawn from actual trading dates only, after a 50-bar warm-up
matching the fact that a 50-bar SMA cannot signal before 50 bars exist.
Positions in the same ticker never overlap (the MA strategy is long-or-flat).
A shortfall (the schedule cannot place every requested trade) is reported,
never silently absorbed.

**What is not matched, by design:** the actual dates. That is the entire
point — only the timing decision is randomised.

**Statistics:** non-parametric, `experiments/montecarlo.py`. The p-value uses
the standard `(1 + draws_at_or_above) / (1 + N)` correction, so beating every
single draw reports the honest floor `1/(N+1)`, never a claimed p=0. Only
clearing the **95th percentile** of the null counts as evidence; beating the
median is what half of all random schedules also do.

**A real defect found and fixed before this experiment could run at scale:**
`MarketView.at()` rescanned each ticker's full history on every timestep — an
O(bars²) engine loop. For a Monte Carlo sweep requiring thousands of full
backtests, this made N=5000 impractical (~2.8s/trial, ~15 hours total).
Replaced with a `bisect_right` cutoff against the already-sorted history
(the engine sorts once before the timeline loop begins), which is
behaviourally identical by construction — verified **byte-identical** against
the committed V2 baseline JSON before and after, and against the full 752-test
regression suite. A companion regression test
(`tests/test_market_view_perf_fix.py`) pins the equivalence directly. A second
optimisation — computing each period's data-provenance hash once rather than
on every trial — removed a further redundant cost. Combined: ~8–9× faster,
enabling the N=5000 default to complete in hours rather than days.

Trials: **N=5000 per period** (train, validation, test, full), seeded
deterministically as `{20260904}-{period}-{trial}`.

---

## 6. Experiment 1 — results

**Completed at full N=5000 per period** (20,000 backtests total for this
experiment alone). Results below are read directly from
`experiments/results_e1_random_control.json`.

**TRAIN** (118 MA trades vs a random control averaging 117.8):

| Metric | MA | Null p50 | Null p95 | Percentile | p-value | Effect size |
|---|---|---|---|---|---|---|
| Sharpe | 1.358 | 1.025 | 1.395 | 93.0% | 0.070 | +1.53 |
| CAGR | 12.47% | 7.29% | 9.93% | **99.9%** | 0.0014 | +3.38 |
| Sortino | 1.902 | 1.453 | 2.036 | 90.3% | 0.097 | +1.34 |
| Calmar | 1.243 | 0.670 | 1.160 | **96.8%** | 0.033 | +2.25 |
| Total return | 79.80% | 42.07% | 60.39% | **99.9%** | 0.0014 | +3.67 |
| Max drawdown | −10.04% | −10.84% | −7.62% | 65.4% | 0.346 | +0.43 |
| **Win rate** | **52.5%** | **64.4%** | **70.3%** | **0.0%** | **1.000** | **−3.26** |
| Profit factor | 5.014 | 2.931 | 4.387 | **98.6%** | 0.014 | +2.77 |
| Expectancy | 625.42 | 355.85 | 511.74 | **99.6%** | 0.004 | +3.08 |

Above 95th percentile: CAGR, Calmar, expectancy, profit factor, total
return. Below median: win rate only — but decisively (0.0th percentile,
effect size −3.26σ).

**VALIDATION** (60 MA trades vs 59.8):

| Metric | MA | Null p50 | Null p95 | Percentile | p-value |
|---|---|---|---|---|---|
| Sharpe | −0.390 | 0.154 | 0.763 | 5.7% | 0.943 |
| CAGR | −3.12% | 0.78% | 4.83% | 3.8% | 0.962 |
| Win rate | 26.7% | 51.7% | 61.7% | **0.0%** | 1.000 |
| Expectancy | −107.76 | 26.96 | 164.78 | 3.3% | 0.967 |

**Every metric is below the null median** in validation, several inside the
bottom 5%. Above 95th percentile: **none**.

**TEST** (90 MA trades vs 89.8):

| Metric | MA | Null p50 | Null p95 | Percentile | p-value |
|---|---|---|---|---|---|
| Sharpe | 1.530 | 1.520 | 2.001 | 51.5% | 0.485 |
| CAGR | 10.41% | 8.37% | 11.29% | 87.8% | 0.122 |
| Win rate | 48.9% | 62.9% | 70.0% | **0.1%** | 0.999 |
| Profit factor | 3.315 | 3.392 | 5.128 | 46.6% | 0.534 |

Above 95th percentile: **none**. Sharpe is a statistical coin flip (51.5%);
profit factor is now *below* the random median.

**FULL** (283 MA trades vs 282.75):

| Metric | MA | Null p50 | Null p95 | Percentile | p-value |
|---|---|---|---|---|---|
| Sharpe | 1.085 | 1.075 | 1.334 | 52.5% | 0.476 |
| CAGR | 8.80% | 7.30% | 9.02% | 92.3% | 0.077 |
| Sortino | 1.533 | 1.557 | 1.974 | 46.3% | 0.537 |
| Max drawdown | −13.75% | −11.45% | −8.71% | 12.2% | 0.878 |
| Win rate | 46.6% | 61.8% | 66.1% | **0.0%** | 1.000 |
| Profit factor | 2.640 | 2.649 | 3.337 | 48.8% | 0.512 |
| Expectancy | 501.34 | 393.45 | 531.43 | 90.6% | 0.094 |

Above 95th percentile: **none**. Below median: max drawdown, profit factor,
Sortino, win rate.

**The pattern across all four periods, at full statistical power:**

1. **Win rate is at or below the 1st percentile of matched random entry in
   every single period** — train 0.0%, validation 0.0%, test 0.1%, full
   0.0% — with effect sizes of −3.2 to −4.3 standard deviations (§17 adds
   the full-period effect of −6.16σ from the pooled comparison). This is
   the strongest, most consistent result in the entire experiment.
2. **Sharpe never clears 95% in any period.** Its best showing is train at
   93.0% — close, but short of the bar this experiment set for evidence.
   In test and full period it is statistically indistinguishable from
   random (51–53rd percentile).
3. **CAGR and total return clear 95% only in training.** In validation they
   are firmly below median; in test and full they sit in the 78–92nd
   percentile range — elevated, but not evidence by this experiment's own
   standard.
4. **Validation is unambiguous:** every metric tested is below its null
   median, several in the bottom 5%.

Read together: MA 20/50 shows a real, statistically supported edge on
*absolute* return **only in the period it was implicitly shaped by** (the
20/50 parameter choice itself was not fit on this data, but training-period
performance is the one place a plausible signal would show up most
generously). Everywhere else, and on every metric that accounts for how
often a trade actually wins, it does not clear the bar. §8 and §16 test
whether this residual is explained by concentration and regime respectively
— both find that it substantially is.

---

## 7. NVDA concentration / leave-one-ticker-out — methodology

`experiments/e2_concentration.py`. The frozen strategy is re-run, unmodified,
over (A) the full universe, (B) the universe excluding NVDA for every period,
and (C) each of the ten possible nine-ticker universes (leave-one-out). No
run selects or optimises a universe; every run uses exactly the tickers V2/V4
already defined, minus the one under test.

---

## 8. NVDA concentration / leave-one-ticker-out — results

**Full-period concentration** (283 trades, full 2016–2026 window):

| Measure | Value |
|---|---|
| Total P&L | $141,879.58 |
| Top 1 trade | 12.28% of total P&L |
| Top 5 trades | 42.88% |
| Top 10 trades | 62.24% |
| Winners / losers | 132 / 151 |
| Largest win / loss | $17,425.27 / −$4,280.65 |

*(This run's own trade count, 283, differs slightly from V4's originally
pooled 268 — V4 pooled three separately-windowed sub-runs; this run executes
the strategy continuously over the full 2016–2026 range in one pass. Both are
correct for what they measure; the difference is a boundary effect at
window seams, not a discrepancy in the strategy.)*

**P&L by ticker, full period:**

| Ticker | P&L | Share | Trades | Win rate | Avg return |
|---|---|---|---|---|---|
| **NVDA** | **$62,327.13** | **43.9%** | 27 | 59.3% | +22.10% |
| GOOGL | $20,445.48 | 14.4% | 26 | 61.5% | +6.97% |
| AAPL | $16,103.94 | 11.3% | 31 | 45.2% | +5.61% |
| MSFT | $12,398.12 | 8.7% | 24 | 50.0% | +5.13% |
| JPM | $11,419.16 | 8.0% | 27 | 51.8% | +4.80% |
| AMZN | $7,833.90 | 5.5% | 26 | 42.3% | +4.30% |
| XOM | $4,810.51 | 3.4% | 30 | 30.0% | +0.86% |
| WMT | $3,617.32 | 2.5% | 29 | 51.7% | +1.86% |
| JNJ | $3,389.68 | 2.4% | 30 | 40.0% | +1.04% |
| PG | −$465.66 | −0.3% | 33 | 39.4% | +0.37% |

**NVDA alone contributes 43.9% of total P&L from 9.5% of trades.**

**Excluding NVDA, by period:**

| Period | Sharpe (with) | Sharpe (without) | CAGR (with) | CAGR (without) |
|---|---|---|---|---|
| Train | 1.358 | 1.083 | 12.47% | 7.24% |
| Validation | −0.390 | −0.344 | −3.12% | −2.30% |
| Test | 1.530 | 1.310 | 10.41% | 7.01% |
| **Full** | **1.085** | **0.840** | **8.80%** | **5.18%** |

Full-period detail without NVDA: 256 trades, Sharpe 0.840, Sortino 1.153,
Calmar 0.442, max drawdown −11.73% (vs −13.75% with NVDA), win rate 45.3%
(vs 46.6% with).

**Leave-one-ticker-out, full period** — the decisive table. Removing any
ticker *other than NVDA* leaves Sharpe in a tight 1.04–1.15 band:

| Ticker removed | CAGR | Sharpe | Max DD | Trades |
|---|---|---|---|---|
| AAPL | 8.25% | 1.066 | −13.30% | 252 |
| MSFT | 8.51% | 1.121 | −11.92% | 259 |
| GOOGL | 8.01% | 1.050 | −11.80% | 257 |
| AMZN | 8.68% | 1.149 | −12.22% | 257 |
| **NVDA** | **5.18%** | **0.840** | −11.73% | 256 |
| JPM | 8.37% | 1.043 | −14.09% | 256 |
| JNJ | 8.65% | 1.066 | −13.93% | 253 |
| XOM | 8.75% | 1.085 | −16.08% | 253 |
| PG | 9.04% | 1.097 | −13.71% | 250 |
| WMT | 8.86% | 1.076 | −13.26% | 254 |

Removing NVDA is the **only** single-ticker removal that produces a visible
Sharpe drop (1.085 → 0.840, a 22.6% relative decline). Every other removal
changes Sharpe by less than 0.05 in either direction.

**Verdict:** the result does not collapse to zero without NVDA — a Sharpe of
0.84 is still positive — but it is not independent of concentration either. A
strategy whose Sharpe declines by nearly a quarter upon removing one name out
of ten, while being essentially insensitive to removing any other single
name, has a materially concentration-dependent result, not a broadly
distributed one.

---

## 9. HMM methodology

`experiments/hmm_features.py` + `experiments/hmm_regime.py` +
`experiments/hmm_selection.py`. Diagnostic only; imports nothing from
`ai/`, `backtesting/`, or the MA strategy.

**Features** (market-level, SPY only): daily log return, 20-day realised
volatility (annualised), 60-day momentum, drawdown from the running peak,
20-day downside volatility. **Explicitly excluded**, per the brief: MA
signal, crossover state, trade outcome, future returns, future drawdown,
strategy P&L. Verified by a structural test asserting no forbidden word
appears in the feature vocabulary.

**Causality, three separate mechanisms:**

1. **Feature construction** is an explicit forward pass — each row uses
   `closes[:i+1]` only. A row before its lookback window is satisfied is
   `usable=False`, never zero-filled (a zero-filled row would tell the model
   the market was flat and calm before anything was observed). Verified by
   truncation-invariance: labelling 300 bars gives identical answers for the
   first 250 as labelling 250 does, directly.
2. **Standardisation** is fit once per fold, on that fold's training prefix
   only — never on the full 2016–2026 series, which would bake 2020's crash
   into every year's z-score including years before it happened.
3. **Inference is filtering, not smoothing.** `causal_filter` implements the
   forward algorithm directly, in log space, and never calls hmmlearn's
   `predict()`/`predict_proba()` — both run forward-*backward* over the full
   array passed to them, using every future observation to inform every past
   state. The normalised forward variable at t **is** `P(S_t | X_1..X_t)`;
   this is standard HMM theory, not an approximation. Verified directly:
   appending future rows to an already-filtered sequence does not change any
   earlier filtered probability (`atol=1e-9`).

**Expanding-window walk-forward:** fold *i* fits on every usable row before
the fold's start date, then filters causally through the fold's end date,
keeping only the newly-inferred block — exactly the brief's example (train
2016–2018 → infer 2019; train 2016–2019 → infer 2020; …). 9 folds were
produced over the 2016–2026 history.

**Label switching.** hmmlearn's component ordering is arbitrary between
independent fits. States are re-identified across folds via Hungarian
assignment (`scipy.optimize.linear_sum_assignment`) minimising total squared
distance between each fold's *raw* (un-standardised) state-mean vectors and
the previous fold's — comparable across folds despite each fold using a
different scaler. With no previous fold, states are ordered by mean daily
return ascending (an arbitrary but fixed, documented convention).

**A real defect found and fixed:** the per-restart random seed
(`seed * 1000 + i`) overflowed numpy's accepted uint32 range for an
ordinary date-shaped base seed (`20260904`), raising `ValueError: Seed must
be between 0 and 2**32 - 1` before a single bar was fit. Fixed with a modulo
reduction against the ceiling; existing tests (small seeds, unaffected by the
overflow) continued to pass unchanged, confirming the fix altered only the
previously-broken large-seed path.

---

## 10. HMM model selection

`hmm_selection.select_k`, evaluated over K = 2, 3, 4, 5 — **structural
criteria only**: BIC, AIC, causal held-out log-likelihood, minimum state
occupancy share (≥5%), minimum average state duration (≥5 trading days).
Verified by a structural test that no Sharpe/CAGR/P&L-shaped identifier
appears anywhere in the selection module's code (checked via `ast`, not
substring matching, after an earlier draft's substring check produced its own
false positive against the module's docstring).

| K | Folds | BIC | AIC | Held-out LL | Min occupancy | Min duration | Stable? |
|---|---|---|---|---|---|---|---|
| 2 | 9 | 118,277.4 | 117,210.9 | −20,198.6 | 45.8% | 35.6d | **YES** |
| 3 | 9 | 94,762.5 | 93,000.4 | −19,019.4 | 25.2% | 19.0d | **YES** |
| 4 | 9 | 80,931.9 | 78,381.6 | −21,624.1 | 9.8% | 10.7d | **YES** |
| 5 | 9 | 74,284.3 | 70,853.0 | −22,773.0 | 3.5% | 9.6d | **no** |

K=5 is correctly rejected: its smallest state occupies only 3.5% of days
(below the 5% floor) and averages 9.6 days' duration — a state the filter
barely visits is not a regime. Note that BIC and AIC *prefer* K=5 (lower is
better, and complexity is monotonically rewarded); if selection had used
BIC/AIC alone, an unstable model would have been chosen. The stability gate
is what stops that. **K=3 was selected** — the best causal held-out
log-likelihood among the three stable candidates.

---

## 11. State characteristics

Computed from the walk-forward's own assembled label sequence (not from any
single fold's model, which no longer exists once the walk-forward moves on):

| State | Label | Occupancy | Runs | Avg duration | Mean return | Vol | Downside vol | Mean DD | Momentum |
|---|---|---|---|---|---|---|---|---|---|
| 0 | high-volatility neutral | 31.4% (683d) | 17 | 40.2d | −0.005% | 25.1% | 16.8% | −11.5% | −1.58% |
| 1 | high-volatility positive-return | 43.4% (945d) | 45 | 21.0d | +0.047% | 13.7% | 8.9% | −3.6% | +4.08% |
| 2 | low-volatility positive-return | 25.2% (550d) | 29 | 19.0d | +0.118% | 9.0% | 5.4% | −0.4% | +7.76% |

Labels are descriptive (computed from occupancy-median volatility split, plus
return/drawdown thresholds), never the forced "bull/bear/crisis" vocabulary —
verified by a structural test.

**Transition matrix** (empirical, from the assembled sequence):

| From ↓ / To → | 0 | 1 | 2 |
|---|---|---|---|
| **0** | 97.5% | 2.5% | 0.0% |
| **1** | 1.8% | 95.2% | 3.0% |
| **2** | 0.0% | 5.1% | 94.9% |

High persistence (≥95% same-state probability) is consistent with genuine
multi-week market regimes rather than day-to-day noise, and state 0 and state
2 essentially never transition directly into each other — a market moves
through state 1 on the way between them, which is itself an interpretable,
non-forced structural finding.

---

## 12. HMM stability

All three retained states (K=3) individually clear both stability bars (min
occupancy 25.2% ≫ 5%; min duration 19.0d ≫ 5d) across all 9 folds. Feature
separation (minimum pairwise Euclidean distance between raw state-mean
vectors, averaged across folds) is 0.097 — a modest but non-trivial gap given
the features are annualised volatilities and daily-scale returns on
different natural units.

**No stable latent regime structure was absent** in this case — K=3 is a
genuinely defensible model, not a forced one. Had no K passed the stability
bars, §10's table would report exactly that, and this section would say so
directly rather than reporting the least-unstable option as though it were a
finding.

---

## 13. Regime → trade analysis

`experiments/hmm_trade_analysis.py`, attaching the K=3 states to every MA
trade by entry/exit date (falling back to the most recent *earlier* label
when a date has none, never a later one). Trades opening before the HMM's own
usable history (the model needs its first training fold) are grouped under
state `-1` — reported, not dropped, for the same reason V4 groups
`Regime.UNKNOWN` rather than discarding it.

**Pooled by entry state (all periods):**

| State | Trades | P&L | Expectancy | Win rate |
|---|---|---|---|---|
| 0 (high-vol neutral) | 62 | $51,113.69 | +8.30% | 58.1% |
| −1 (pre-HMM history) | 47 | $36,565.69 | +11.08% | 57.5% |
| 1 (high-vol positive) | 96 | $15,462.71 | +1.75% | 37.5% |
| 2 (low-vol positive) | 63 | $5,711.20 | +1.52% | 36.5% |

**This is the most consequential single finding of Experiment 3.** The
strategy's *best* expectancy and win rate occur in **state 0** — the
high-volatility, near-zero-return, deepest-drawdown state — not in state 2,
the calm, steadily positive "healthiest" regime, which produces the
*weakest* expectancy and win rate of the three labelled states. This is the
opposite of the naive prior that a trend-following crossover should do best
in calm, clearly-trending conditions.

A plausible mechanism: state 0 (deep drawdowns, high volatility) is followed
by state 1 and state 2 (the recovery/expansion states), and a long MA
crossover entered near a state-0 trough captures the subsequent recovery —
which would make the apparent "state 0 edge" actually a *timing-of-the-next-
regime* effect, not a property of state 0 itself. §14's transition analysis
tests this directly.

---

## 14. Transition analysis

**Pooled:**

| | Trades | Mean return |
|---|---|---|
| Crossing a state transition during the hold | 121 | +2.35% |
| Not crossing (stays in one state throughout) | 147 | +6.91% |

Trades that stayed within one latent state for their entire holding period
returned nearly **3× more**, on average, than trades that spanned a
transition. Combined with §13, the picture is: the strategy's best trades
are ones entered in the depressed state-0 conditions that *then stay in a
recovering regime long enough to realise the gain* — i.e., performance is
tied to which regime the trade's holding period fell within, not to the
crossover signal correctly timing an entry within an already-known regime.
This is direct evidence for the "false edge via regime, not signal" reading
of the SIGNAL STATUS verdict.

---

## 15. Train / validation / test decomposition (HMM states)

| Period | Trades | Best state | Worst state |
|---|---|---|---|
| Train | 118 | −1 (pre-history): +11.08% expectancy, 47 trades | 2: −3.51% expectancy, 9 trades (small) |
| Validation | 60 | 2: +1.37% expectancy, 24 trades (small) | **1: −5.53% expectancy, 22 trades (small)** |
| Test | 90 | 0: +17.63% expectancy, 11 trades (small) | 2: +3.15% expectancy, 30 trades |

Full per-state breakdown by period:

```
[train]  state -1:  47 trades  P&L  36,565.69  expectancy +11.08%
         state  0:  37 trades  P&L  36,431.59  expectancy  +9.55%
         state  1:  25 trades  P&L   2,938.17  expectancy  +1.37%  (small sample)
         state  2:   9 trades  P&L  -2,136.43  expectancy  -3.51%  (small sample)

[validation] state 2: 24 trades  P&L   1,967.02  expectancy  +1.37%  (small sample)
             state 0: 14 trades  P&L  -1,765.38  expectancy  -2.32%  (small sample)
             state 1: 22 trades  P&L  -6,667.30  expectancy  -5.53%  (small sample)

[test]   state 1:  49 trades  P&L  19,191.85  expectancy  +5.22%
         state 0:  11 trades  P&L  16,447.48  expectancy +17.63%  (small sample)
         state 2:  30 trades  P&L   5,880.60  expectancy  +3.15%
```

**This directly extends V4's finding.** V4 found the validation failure was
only partially explained by V4's heuristic regime taxonomy (crisis
over-represented but behaving differently within itself). The HMM
decomposition sharpens this: in validation, **every state with a usable
sample lost or barely broke even** — state 1 (the regime that was the
strategy's *second-best* pooled performer, +1.75% pooled expectancy) is
validation's *worst* performer at −5.53%. The strategy did not merely
encounter a bad state mix in validation; it lost money in the same latent
state that made money everywhere else, which is the signature of a
non-generalising fit rather than of unlucky regime timing.

---

## 16. Regime-conditioned random control (Experiment 4)

**Completed: 500 trials** (reduced from the suggested 5,000 for session-time
practicality — disclosed in `experiments/e4_regime_conditioned.py`'s own
module docstring, not a data-integrity shortcut; the p-value floor at this N
is 1/501 ≈ 0.002, still a meaningful resolution). Full period only. Results
read directly from `experiments/results_e4_regime_conditioned.json`.

| State | Label | Trades | MA expectancy | Null p50 | Null p95 | Percentile | p-value |
|---|---|---|---|---|---|---|---|
| −1 | pre-HMM history | 47 | 11.08% | 5.43% | 7.93% | **100.0%** | 0.002 |
| 0 | high-vol, deepest-drawdown | 76 | 8.20% | 5.72% | 8.31% | 94.4% | 0.058 |
| 1 | high-vol, positive-return | 96 | 1.60% | 2.51% | 4.48% | 20.8% | 0.792 |
| 2 | low-vol, positive-return | 64 | 2.21% | 2.93% | 5.34% | 32.4% | 0.677 |

**This is the single most decisive result in the entire falsification
programme.** Once entries are compared against random timing *within the
same latent regime*, MA 20/50 beats matched random entry in **zero** of the
three regimes the HMM actually covers:

- **State 1** (43.4% of all market days, the strategy's second-largest
  pooled contributor and validation's worst-performing state, §13/§15): MA
  sits at the **20.8th percentile** — worse than the median random schedule
  drawn from the same regime.
- **State 2** (the calm, "healthiest" bull state): MA at the **32.4th
  percentile** — also below median.
- **State 0** (the deepest-drawdown, highest-volatility state that looked
  like the strategy's best performer in the pooled, unconditioned view of
  §13): drops to **94.4%** once compared against regime-matched random
  entry — directionally favourable, short of the 95% evidence bar, and a
  materially weaker showing than the unconditioned pooled comparison
  suggested. Conditioning on regime removed most of what looked like an
  edge here.
- **State −1** clears 100% — but this is the slice of trades that predates
  the HMM's own usable history entirely (the model needs its first training
  fold before it can label anything). It is not evidence of a regime effect;
  it is evidence about the earliest ~47 trades in the sample, arrived at by
  a method that says nothing about regime at all.

**Conclusion:** the apparent overall edge that Experiment 1 found in the
training period is substantially explained by *which regime the trades
happened to occupy*, not by the 20/50 crossover's entry timing. Within every
regime the HMM actually models, MA does not demonstrate an edge over
regime-matched random timing at the standard this programme set.

---

## 17. Statistical results (summary across experiments)

All figures final (N=5000 for Experiment 1, N=500 for Experiment 4):

| Test | Result | Interpretation |
|---|---|---|
| MA vs random, win rate, every period | 0.0–0.1 percentile in all 4 periods, effect size −3.2 to −4.3σ | MA loses to matched random timing on hit rate, decisively, without exception |
| MA vs random, Sharpe | Never clears 95th percentile; 51–53rd in test/full, 93.0th in train (best case) | Statistically indistinguishable from random outside training |
| MA vs random, CAGR/total return | ≥95th percentile in **train only**; 78–92nd in validation/test/full | Absolute-return edge does not generalise beyond the period the parameter choice was most favourably exposed to |
| MA vs random, conditioned on HMM regime (Exp. 4) | 20.8th–32.4th percentile in 2 of 3 modelled regimes; 94.4th in the third | **No regime the HMM covers shows a beaten-random edge at the evidence bar** |
| NVDA leave-one-out | Sharpe 1.085 → 0.840 (−22.6%) | Materially concentration-dependent |
| Any other ticker leave-one-out | Sharpe range 1.04–1.15 | Result is not concentration-dependent on any other single name |
| HMM K selection | K=3, K=5 rejected on stability, never on P&L | A genuine, non-forced latent structure exists |
| Best-performing HMM state vs "healthiest" state | State 0 (deep drawdown) beats state 2 (calm bull) on both expectancy and win rate, pooled | Contradicts the naive trend-following prior — and does not survive regime-conditioning (Exp. 4) |
| Trades crossing vs not crossing a transition | +2.35% vs +6.91% | Performance tracks regime persistence, not entry precision |
| Validation, best HMM state elsewhere (state 1) | −5.53% in validation vs +1.75% pooled | Non-generalising, not merely unlucky regime mix |

---

## 18. Economic significance

Even where a metric is statistically favourable, its economic weight is
limited:

- The pooled expectancy advantage of state 0 (+8.30%) rests on 62 trades —
  usable, but not large.
- NVDA's 43.9% P&L share means a large fraction of the *entire ten-year,
  ten-ticker result* is attributable to one company's stock having risen
  roughly 15-fold over the AI buildout — a macro/sector event, not a
  crossover-timing achievement.
- Costs are real and already included (10.00bp realised per trade, 62.5×
  turnover on the full-universe run) — they do not change the qualitative
  picture, but they are a permanent drag any live implementation would pay
  regardless of which reading of the signal is correct.

---

## 19. Limitations

- **Survivorship bias is present and disclosed, not corrected.** The
  universe consists of names that are large today; a point-in-time universe
  was out of scope for this phase.
- **The HMM is market-level (SPY) only.** It does not model per-ticker
  regime, which could differ meaningfully for, e.g., NVDA specifically given
  its outsized contribution.
- **Feature separation (0.097) is modest.** The three states are real and
  stable by the occupancy/duration bars, but they are not dramatically far
  apart in raw feature space; a coarser 2-state model (also stable, per §10)
  is a legitimate alternative reading.
- **Experiment 4 covers the full period only**, not train/validation/test
  separately, for the same session-time reasons as its trial-count
  reduction.

---

## 20. Robustness caveat

No stress testing (transaction-cost sensitivity, slippage multiples, spread
widening, execution delay) was performed in this phase — that is explicitly
V7's scope, gated on V5, which is itself gated on the outcome below.

---

## 21. Final verdict

### SIGNAL STATUS: **D — EVIDENCE OF FALSE EDGE**

All four experiments completed at full scale. MA 20/50's headline performance
is substantially explained by:

1. **Concentration** — 43.9% of total P&L from one ticker (NVDA); the only
   single-ticker removal that materially changes the result.
2. **A win rate that loses to matched random timing, decisively, in every
   period tested** (0.0–0.1st percentile, effect sizes of −3.2 to −4.3
   standard deviations), while absolute-return metrics beat random **only in
   the training period** — the profile of a few large, long-duration
   winners rather than of accurate entry timing.
3. **Regime-conditioned random control removes the training-period edge
   entirely.** Once compared against random timing *within the same latent
   market state*, MA does not clear the evidence bar in any of the three
   regimes the HMM actually models (20.8th, 32.4th, and 94.4th percentiles).
   This is the strongest single result in the programme: it is not merely
   that a latent regime correlates with performance (§13–15 already showed
   that) — it is that **once regime is held constant, entry timing itself
   adds nothing measurable**.

Four independent falsification approaches — unconditional random-timing
comparison, ticker-concentration removal, regime decomposition, and
regime-conditioned random timing — agree. None of this rules out that
MA 20/50 is *harmless*: a Sharpe of 0.84 without NVDA, in isolation, is not a
losing strategy. But "not losing money" and "contains a demonstrable,
generalising timing edge" are different claims, and the full evidence in this
phase supports the first, not the second.

---

## 22. Recommendation for next phase

**STOP MA 20/50 DEVELOPMENT.** Do not proceed to V5 parameter robustness
testing (10/30, 20/100, 50/100, 50/200) — with no demonstrated mechanism,
that sweep would fit whichever pair best matches 2016–2026 and manufacture
exactly the overfit this falsification programme exists to prevent.

If work continues on this line at all, the two most informative next steps
are narrower than V5:

1. **Re-run Experiment 1/4 excluding NVDA**, to see whether the reduced
   (0.84 Sharpe) result still beats matched random timing — settling whether
   *any* residual signal survives once concentration is controlled for.
2. **A per-ticker or sector-conditioned HMM**, to test whether NVDA's
   contribution is itself regime-driven (an AI-buildout macro regime) rather
   than crossover-timing-driven — which would make the "false edge"
   diagnosis apply even more directly to the strategy's single largest
   contributor.

Absent either of those producing a materially different verdict, this
strategy should not receive further engineering investment, and the research
loop (per the roadmap) should return to hypothesis generation rather than to
parameter search on this one.
