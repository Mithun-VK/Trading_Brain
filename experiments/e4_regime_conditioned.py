"""Experiment 4 — regime-conditioned random control.

The strongest single falsification test in the whole programme. Experiment
1 asked whether MA timing beats random timing overall. This asks the
sharper question: does it still beat random timing **after conditioning on
the latent market regime** -- i.e., is the apparent edge actually about
*when within a regime* to enter, or is it fully explained by *which regime*
the trades happened to fall in?

Method: the same matched random-entry schedule generator from
`random_control.py`, drawing `trials` full-period schedules. Each draw's
trades are labelled with the *same* HMM states used for the MA arm (states
are a property of the market, computed once, never of either strategy), and
grouped the same way. The MA arm's per-state expectancy is then placed
against the empirical null built from the random draws' per-state
expectancy, using the same non-parametric comparison as Experiment 1.

**Scope, disclosed rather than hidden.** The brief asks for this "if
computationally practical." Experiment 1's full-period Monte Carlo alone
takes several hours in this environment; a regime-conditioned version at
the same N would cost the same again, on top of it. This runs at a reduced
trial count (default 500, configurable) over the full period only. That is
a session-time constraint, not a data-integrity shortcut -- and it is
recorded in the output so nobody mistakes 500 draws for 5,000.

Run:  python -m experiments.e4_regime_conditioned [trials]
"""

from __future__ import annotations

import json
import random
import sys
import time

from backtesting.strategy import MovingAverageCrossStrategy
from experiments import (
    data,
    hmm_selection,
    hmm_trade_analysis,
    montecarlo,
    random_control,
    runner,
    trade_analysis,
)
from experiments.config import Period
from experiments.hmm_features import causal_features, usable_prefix
from experiments.hmm_regime import walk_forward
from experiments.v2_baseline import BENCHMARK, HISTORY_END, HISTORY_START, UNIVERSE, config

DEFAULT_TRIALS = 500
BASE_SEED = 20260905
FULL = Period("full", HISTORY_START, HISTORY_END)


def main(argv: list[str]) -> int:
    trials = int(argv[1]) if len(argv) > 1 else DEFAULT_TRIALS

    print("Loading market data (Yahoo, cached)...")
    all_bars = data.align(data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END))
    strategy_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}
    window = {
        t: [b for b in s if FULL.contains(b.ts.date())] for t, s in strategy_bars.items()
    }
    provenance = runner.describe_data(window, provider="yahoo")

    print("Rebuilding the K=3 HMM regime labels (same method as Experiment 3)...")
    feature_rows = causal_features(all_bars[BENCHMARK])
    usable = usable_prefix(feature_rows)
    rows_by_date = {r.date: r.values for r in usable}
    wf = walk_forward(feature_rows, k=3, seed=20260904)
    labels_by_date = wf.labels_by_date()
    states = hmm_selection.characterize(wf, rows_by_date)
    print(f"  {len(states)} states, {len(labels_by_date)} labelled days")

    ma_run = runner.run(
        config("ma_cross", {"fast": 20, "slow": 50}),
        MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(UNIVERSE)),
        window, provider="yahoo", period="full", provenance=provenance,
    )
    assert ma_run.result is not None
    ma_records = trade_analysis.enrich(ma_run.result, window)
    ma_enriched = hmm_trade_analysis.attach(ma_records, labels_by_date)
    ma_by_state = {s.state: s for s in hmm_trade_analysis.by_state(ma_enriched)}
    target = random_control.target_from(ma_records, window)

    print(f"\nRunning {trials} matched random trials, grouped by regime state...")
    null_by_state: dict[int, list[float | None]] = {}
    started = time.perf_counter()
    for trial in range(trials):
        rng = random.Random(f"{BASE_SEED}-e4-{trial}")
        plan = random_control.build_plan(target, window, rng)
        control = runner.run(
            config("random_entry"), random_control.RandomEntryStrategy(plan),
            window, provider="yahoo", period="full", provenance=provenance,
        )
        assert control.result is not None
        control_records = trade_analysis.enrich(control.result, window)
        control_by_state = hmm_trade_analysis.by_state(
            hmm_trade_analysis.attach(control_records, labels_by_date)
        )
        for stat in control_by_state:
            null_by_state.setdefault(stat.state, []).append(stat.expectancy)
        if trial and trial % 100 == 0:
            rate = trial / (time.perf_counter() - started)
            print(f"    {trial}/{trials} ({rate:.1f}/s)")

    comparisons = {}
    for state_id, ma_stat in sorted(ma_by_state.items()):
        null = null_by_state.get(state_id, [])
        comparisons[state_id] = montecarlo.compare(
            f"state_{state_id}_expectancy", ma_stat.expectancy, null
        )

    _report(trials, ma_by_state, comparisons, states)

    payload = {
        "trials": trials,
        "note": (
            f"Reduced from the suggested 5000 to {trials} for session-time "
            "practicality; disclosed, not a data-integrity shortcut."
        ),
        "states": [s.to_dict() for s in states],
        "ma_by_state": {str(k): v.to_dict() for k, v in ma_by_state.items()},
        "comparisons": {str(k): v.to_dict() for k, v in comparisons.items()},
    }
    out = "experiments/results_e4_regime_conditioned.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWritten: {out}")
    return 0


def _fmt(v, digits=4) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _report(trials, ma_by_state, comparisons, states) -> None:
    labels = {s.state_id: s.label for s in states}
    print("\n" + "=" * 100)
    print(f"EXPERIMENT 4 — MA vs RANDOM ENTRY, CONDITIONED ON HMM REGIME ({trials} trials)")
    print("=" * 100)
    print(f"{'state':>7}{'label':<32}{'trades':>8}{'MA exp':>10}{'null p50':>10}"
          f"{'pctile':>9}{'p-value':>10}")
    for state_id, ma_stat in sorted(ma_by_state.items()):
        c = comparisons[state_id]
        label = labels.get(state_id, "unlabelled (pre-HMM history)")
        pct = c.percentile
        pct_text = "n/a" if pct is None else f"{pct*100:.1f}%"
        print(f"{state_id:>7}{label:<32}{ma_stat.trades:>8}{_fmt(ma_stat.expectancy):>10}"
              f"{_fmt(c.null_median):>10}{pct_text:>9}{_fmt(c.p_value):>10}")

    print("\nREADING THIS TABLE")
    print("  Beating random entry WITHIN a regime is stronger evidence than beating it")
    print("  overall (Experiment 1) -- it rules out 'the edge is just being in the")
    print("  right regime' as the explanation.")
    above_95 = [
        s for s, c in comparisons.items()
        if c.percentile is not None and c.percentile >= 0.95
    ]
    print(f"\n  States where MA beat the 95th percentile of random: {above_95 or 'NONE'}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
