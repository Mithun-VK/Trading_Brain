"""Experiment 3 runner — causal walk-forward HMM regime detection.

Run:  python -m experiments.e3_hmm

Diagnostic only. The HMM never sees the MA signal, never sees a trade
outcome, and model selection (K=2..5) never sees a Sharpe ratio or a dollar
figure -- see `hmm_selection.select_k`. States are attached to trades only
*after* the model and K have been chosen on structural grounds alone.
"""

from __future__ import annotations

import json
import sys

from backtesting.strategy import MovingAverageCrossStrategy
from experiments import data, hmm_selection, hmm_trade_analysis, runner, trade_analysis
from experiments.config import Period
from experiments.hmm_features import causal_features, usable_prefix
from experiments.hmm_regime import walk_forward
from experiments.v2_baseline import (
    BENCHMARK,
    HISTORY_END,
    HISTORY_START,
    TEST,
    TRAIN,
    UNIVERSE,
    VALIDATION,
    config,
)

K_CANDIDATES = (2, 3, 4, 5)
SEED = 20260904


def _window(bars, period: Period):
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


def main() -> int:
    print("Loading market data (Yahoo, cached)...")
    all_bars = data.align(data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END))
    if BENCHMARK not in all_bars:
        print(f"No {BENCHMARK} data: cannot build market-level HMM features.")
        return 1
    strategy_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}

    # --- features: market-level only, no strategy state anywhere ---
    print("Building causal features (SPY, no MA signal, no trade outcome)...")
    feature_rows = causal_features(all_bars[BENCHMARK])
    usable = usable_prefix(feature_rows)
    print(f"  {len(feature_rows)} bars, {len(usable)} usable after the lookback warm-up")
    rows_by_date = {r.date: r.values for r in usable}

    # --- walk-forward fit + causal filter, for every candidate K ---
    print(f"\nRunning expanding-window walk-forward for K in {K_CANDIDATES}...")
    results = {}
    for k in K_CANDIDATES:
        wf = walk_forward(feature_rows, k, seed=SEED)
        results[k] = wf
        if wf.folds:
            print(f"  K={k}: {len(wf.folds)} folds, "
                  f"held-out log-likelihood {wf.total_held_out_log_likelihood:.1f}")
        else:
            print(f"  K={k}: {wf.skipped_reason}")

    # --- model selection: structure only, never P&L ---
    best_k, candidates = hmm_selection.select_k(results, rows_by_date)
    _report_selection(candidates, best_k)

    if best_k is None:
        print("\n" + "=" * 100)
        print("NO STABLE LATENT REGIME STRUCTURE IDENTIFIED.")
        print("=" * 100)
        print("No K in the candidate set met the occupancy and duration stability bars.")
        print("This is a valid, reportable result -- not a failure of the search.")
        _write({"selection": [c.to_dict() for c in candidates], "selected_k": None})
        return 0

    result = results[best_k]
    states = hmm_selection.characterize(result, rows_by_date)
    transitions = hmm_selection.transition_matrix(result)
    labels_by_date = result.labels_by_date()

    print(f"\nSelected K = {best_k}")
    print("\nSTATE CHARACTERISTICS")
    for s in states:
        print(f"  state {s.state_id}: {s.label}")
        print(f"    occupancy {s.occupancy_share:.1%} ({s.occupancy} days), "
              f"{s.runs} runs, avg duration {s.average_duration_days:.1f}d")
        print(f"    mean return {s.mean_return:+.5f}, vol {s.volatility:.3f}, "
              f"downside vol {s.downside_volatility:.3f}, "
              f"mean drawdown {s.mean_drawdown:.3f}, momentum {s.mean_momentum:+.4f}")

    print("\nTRANSITION MATRIX (empirical, from the assembled walk-forward sequence)")
    for from_state, row in transitions.items():
        print(f"  from {from_state}: " + ", ".join(f"{k}={v:.3f}" for k, v in row.items()))

    # --- attach to MA trades, per period ---
    print("\nAttaching HMM states to MA 20/50 trades...")
    period_payload = {}
    all_enriched = []
    for period in (TRAIN, VALIDATION, TEST):
        window = _window(strategy_bars, period)
        ma_run = runner.run(
            config("ma_cross", {"fast": 20, "slow": 50}),
            MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(UNIVERSE)),
            window, provider="yahoo", period=period.name,
        )
        assert ma_run.result is not None
        records = trade_analysis.enrich(ma_run.result, window)
        enriched = hmm_trade_analysis.attach(records, labels_by_date)
        all_enriched.extend(enriched)
        state_stats = hmm_trade_analysis.by_state(enriched)
        transition_stats = hmm_trade_analysis.analyse_transitions(enriched, labels_by_date)

        period_payload[period.name] = {
            "trades": len(enriched),
            "by_state": [hs.to_dict() for hs in state_stats],
            "transitions": transition_stats.to_dict(),
        }
        print(f"\n  [{period.name}] {len(enriched)} trades")
        for hs in state_stats:
            sig = "" if hs.is_significant else "  (small sample)"
            print(f"    state {hs.state:>3}: {hs.trades:>4} trades, P&L {hs.total_pnl:>12.2f}, "
                  f"expectancy {_fmt(hs.expectancy)}{sig}")

    print("\nPOOLED (all periods) BY STATE")
    pooled_stats = hmm_trade_analysis.by_state(all_enriched)
    for hs in pooled_stats:
        sig = "" if hs.is_significant else "  (small sample)"
        print(f"  state {hs.state:>3}: {hs.trades:>4} trades, P&L {hs.total_pnl:>12.2f}, "
              f"expectancy {_fmt(hs.expectancy)}, win rate {_fmt(hs.win_rate, pct=True)}{sig}")

    pooled_transitions = hmm_trade_analysis.analyse_transitions(all_enriched, labels_by_date)
    print("\nPOOLED TRANSITION ANALYSIS")
    print(f"  crossing a transition:     {pooled_transitions.trades_crossing_a_transition} trades, "
          f"mean return {_fmt(pooled_transitions.mean_return_crossing, pct=True)}")
    print(f"  not crossing:              "
          f"{len(all_enriched) - pooled_transitions.trades_crossing_a_transition} trades, "
          f"mean return {_fmt(pooled_transitions.mean_return_not_crossing, pct=True)}")

    _write({
        "selected_k": best_k,
        "selection": [c.to_dict() for c in candidates],
        "states": [s.to_dict() for s in states],
        "transition_matrix": transitions,
        "by_period": period_payload,
        "pooled_by_state": [s.to_dict() for s in pooled_stats],
        "pooled_transitions": pooled_transitions.to_dict(),
        "trades": [e.to_dict() for e in all_enriched],
    })
    return 0


def _fmt(v, pct=False) -> str:
    if v is None:
        return "n/a"
    return f"{v*100:.2f}%" if pct else f"{v:.4f}"


def _report_selection(candidates, best_k) -> None:
    print("\n" + "=" * 100)
    print("MODEL SELECTION (structure only -- BIC/AIC/held-out LL/occupancy/duration)")
    print("=" * 100)
    print(f"{'K':>3}{'folds':>7}{'BIC':>12}{'AIC':>12}{'held-out LL':>14}"
          f"{'min occ':>10}{'min dur':>9}{'stable?':>9}")
    for c in candidates:
        print(f"{c.k:>3}{c.n_folds:>7}{c.total_bic:>12.1f}{c.total_aic:>12.1f}"
              f"{c.total_held_out_log_likelihood:>14.1f}"
              f"{c.min_occupancy_share*100:>9.1f}%{c.min_average_duration:>9.1f}"
              f"{('YES' if c.passes_stability else 'no'):>9}")
        if c.note:
            print(f"      {c.note}")
    if best_k is not None:
        detail = (
            f"Selected K={best_k}: best causal held-out log-likelihood "
            "among stable candidates."
        )
        print(detail)


def _write(payload: dict) -> None:
    out = "experiments/results_e3_hmm.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    sys.exit(main())
