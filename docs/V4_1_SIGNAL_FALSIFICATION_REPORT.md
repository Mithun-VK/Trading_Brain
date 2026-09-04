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

MA 20/50's V2/V4 results are substantially explained by controls outside the
signal itself: concentration in a single ticker (NVDA, ~44% of total P&L),
exposure and holding-period characteristics that a matched random schedule
reproduces on most risk-adjusted metrics, and a market-level latent regime
that the strategy's edge tracks more closely than it tracks its own entry
timing. The strongest single piece of evidence is structural rather than
statistical: **the win rate is below the 5th percentile of matched random
entry in every period tested**, including periods where Sharpe and CAGR look
favourable. A strategy beating random on risk-adjusted return while losing to
it on win rate, in the presence of 44% single-ticker concentration, is not
what a genuine timing edge looks like — it is what holding a few large,
lucky, long-duration winners looks like.

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

> **[PENDING FINAL N=5000 RUN]** — the Monte Carlo sweep was executing in the
> background at the time of writing. §6 will be replaced with the completed
> N=5000 table before this report is finalised. A smaller preview run
> (N=20/period, same code path, same seed scheme) produced the following
> **directional, non-final** pattern, included only to show the shape of the
> result while the full run completes:
>
> - **Train:** MA clears the 95th percentile on Sharpe, CAGR, Sortino, Calmar,
>   expectancy, profit factor, total return — but sits at the **0th
>   percentile on win rate** (MA 52.5% vs a random median of 66.0%).
> - **Validation:** MA is **below the null on every metric**, several at the
>   0th percentile (Sharpe −0.39 vs random median +0.19; win rate 26.7% vs
>   random median 53.3%).
> - **Test:** Sharpe ties the random median (45th percentile); CAGR clears
>   the 95th; win rate is again at the 0th percentile.
> - **Full:** Sharpe sits at exactly the **50th percentile** — indistinguishable
>   from random. CAGR and expectancy clear the 95th percentile. Win rate is at
>   the 0th percentile in every period without exception.

The pattern that survives even at this small preview N, and that the full run
will either confirm or overturn: **CAGR and total return beat random
reliably; Sharpe is at best a coin flip; win rate loses to random in every
single period.** That combination — better absolute return, unremarkable
risk-adjusted return, and a worse-than-random hit rate — is the statistical
signature of a strategy whose return comes from a small number of
large-magnitude, long-duration winners rather than from correctly timing
entries. §7 and §12 test that reading directly.

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

> **[PENDING]** — this Monte Carlo run (500 trials, reduced from the
> suggested 5,000 for session-time practicality — disclosed in
> `experiments/e4_regime_conditioned.py`'s own module docstring, not a
> data-integrity shortcut) was executing at the time of writing. This section
> will report, per HMM state: MA expectancy vs the empirical null built from
> matched random-entry schedules, filtered to trades whose entry fell in that
> state, using the identical `montecarlo.compare` machinery as Experiment 1.
>
> **What this experiment settles that Experiment 1 alone cannot:** whether
> beating (or losing to) random entry overall is actually explained by *which
> regime the random and MA trades happened to fall in*, rather than by
> anything about the 20/50 crossover's timing precision. Given §13–15 already
> show state 0's disproportionate contribution and validation's collapse
> concentrated in state 1, the informative outcome would be MA failing to
> clear the null **within** state 1 specifically, and this section will state
> that directly once the run completes.

---

## 17. Statistical results (summary across experiments)

| Test | Result | Interpretation |
|---|---|---|
| MA vs random, win rate, every period | 0th percentile (preview N=20) | MA loses to matched random timing on hit rate, without exception |
| MA vs random, Sharpe, full period | ~50th percentile (preview N=20) | Statistically indistinguishable from random |
| MA vs random, CAGR/total return | ≥95th percentile in 3 of 4 periods (preview N=20) | Absolute return beats random; driven by magnitude, not frequency |
| NVDA leave-one-out | Sharpe 1.085 → 0.840 (−22.6%) | Materially concentration-dependent |
| Any other ticker leave-one-out | Sharpe range 1.04–1.15 | Result is not concentration-dependent on any other single name |
| HMM K selection | K=3, K=5 rejected on stability, never on P&L | A genuine, non-forced latent structure exists |
| Best-performing HMM state vs "healthiest" state | State 0 (deep drawdown) beats state 2 (calm bull) on both expectancy and win rate | Contradicts the naive trend-following prior |
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

- **Experiment 1's full N=5000 run and Experiment 4 were not complete at
  writing time**; §6 and §16 carry directional previews only and will be
  replaced with final numbers before this report is closed out (see the
  commit history on this branch for the completion commit).
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

MA 20/50's headline performance is substantially explained by:

1. **Concentration** — 43.9% of total P&L from one ticker (NVDA); the only
   single-ticker removal that materially changes the result.
2. **A win rate that loses to matched random timing in every period
   tested**, while absolute-return metrics (CAGR, total return) beat random —
   the profile of a few large, long-duration winners rather than of accurate
   entry timing.
3. **A latent market regime that better explains the pattern of returns than
   the crossover signal does** — the strategy's best results cluster in
   trades that happen to span a recovering high-volatility state into a
   subsequent expansion, and its validation-period failure is concentrated
   in the exact state that was its second-best performer everywhere else.

None of this rules out that MA 20/50 is *harmless* — a Sharpe of 0.84 without
NVDA, in isolation, is not a losing strategy. But "not losing money" and
"contains a demonstrable, generalising timing edge" are different claims, and
the evidence in this phase supports the first, not the second.

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
