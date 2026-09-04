"""Experiment 1 runner — MA 20/50 against matched random entry.

Run:  python -m experiments.e1_random_control [trials]

The strategy is frozen. Nothing here tunes anything; the experiment is
defined before it is run and is not adjusted after seeing results.
"""

from __future__ import annotations

import json
import random
import sys
import time

from backtesting.strategy import MovingAverageCrossStrategy
from experiments import data, montecarlo, random_control, runner, trade_analysis
from experiments.config import Period
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

DEFAULT_TRIALS = 5_000
BASE_SEED = 20260904

# Fixed before the experiment runs. Sharpe is primary because it is the
# metric least distorted by the exposure differences a random schedule can
# introduce; the others are reported so a divergence between them is visible
# rather than hidden by a single headline number.
METRICS = ("sharpe", "cagr", "sortino", "calmar", "total_return",
           "max_drawdown", "win_rate", "profit_factor", "expectancy")


def _window(bars, period: Period):
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


def _metrics_of(run) -> dict[str, float | None]:
    p = run.performance
    return {name: getattr(p, name, None) for name in METRICS}


def run_period(period: Period, strategy_bars, trials: int) -> dict:
    """Run the MA arm and `trials` matched random arms over one window."""
    window = _window(strategy_bars, period)
    # The bars are identical across every trial in this period -- compute
    # their provenance once rather than re-hashing the whole window on each
    # of the `trials` random draws.
    window_provenance = runner.describe_data(window, provider="yahoo")

    ma_run = runner.run(
        config("ma_cross", {"fast": 20, "slow": 50}),
        MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(UNIVERSE)),
        window, provider="yahoo", period=period.name, provenance=window_provenance,
    )
    assert ma_run.result is not None
    ma_records = trade_analysis.enrich(ma_run.result, window)
    target = random_control.target_from(ma_records, window)

    print(f"  [{period.name}] MA: {target.total_trades} trades, "
          f"median hold {target.median_holding} bars, "
          f"Sharpe {ma_run.performance.sharpe}, "
          f"avg exposure {ma_run.performance.average_exposure}")

    null: dict[str, list[float | None]] = {m: [] for m in METRICS}
    exposures: list[float] = []
    trade_counts: list[int] = []
    shortfalls = 0
    started = time.perf_counter()

    for trial in range(trials):
        # Seed is derived from a fixed base plus the period name and trial
        # index, so a single trial can be reproduced in isolation.
        rng = random.Random(f"{BASE_SEED}-{period.name}-{trial}")
        plan = random_control.build_plan(target, window, rng)
        if random_control.plan_shortfall(target, plan):
            shortfalls += 1

        control = runner.run(
            config("random_entry"),
            random_control.RandomEntryStrategy(plan),
            window, provider="yahoo", period=period.name, provenance=window_provenance,
        )
        for name, value in _metrics_of(control).items():
            null[name].append(value)
        if control.performance.average_exposure is not None:
            exposures.append(control.performance.average_exposure)
        trade_counts.append(control.performance.trade_count)

        if trial and trial % 500 == 0:
            rate = trial / (time.perf_counter() - started)
            print(f"    {trial}/{trials} ({rate:.0f}/s)")

    observed = _metrics_of(ma_run)
    comparisons = {
        name: montecarlo.compare(name, observed[name], null[name]) for name in METRICS
    }

    return {
        "period": period.name,
        "ma": {
            **observed,
            "trades": ma_run.performance.trade_count,
            "average_exposure": ma_run.performance.average_exposure,
            "average_holding_days": ma_run.performance.average_holding_period_days,
        },
        "control": {
            "trials": trials,
            "mean_trades": (
                round(sum(trade_counts) / len(trade_counts), 2) if trade_counts else None
            ),
            "mean_exposure": round(sum(exposures) / len(exposures), 6) if exposures else None,
            "trials_with_shortfall": shortfalls,
        },
        "comparisons": {k: v.to_dict() for k, v in comparisons.items()},
        "verdict": montecarlo.verdict(comparisons),
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }


def main(argv: list[str]) -> int:
    trials = int(argv[1]) if len(argv) > 1 else DEFAULT_TRIALS

    print("Loading market data (Yahoo, cached)...")
    all_bars = data.align(data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END))
    strategy_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}
    print(f"  snapshot {runner.snapshot_bars(strategy_bars)}\n")

    full = Period("full", HISTORY_START, HISTORY_END)
    results = []
    print(f"Running {trials} matched random trials per period...")
    for period in (TRAIN, VALIDATION, TEST, full):
        results.append(run_period(period, strategy_bars, trials))

    _report(results, trials)

    out = "experiments/results_e1_random_control.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1, default=str)
    print(f"\nWritten: {out}")
    return 0


def _fmt(v, pct=False, digits=2) -> str:
    if v is None:
        return "n/a"
    return f"{v*100:.{digits}f}%" if pct else f"{v:.{digits}f}"


def _report(results: list[dict], trials: int) -> None:
    print("\n" + "=" * 104)
    print(f"EXPERIMENT 1 — MA 20/50 vs MATCHED RANDOM ENTRY ({trials} trials/period)")
    print("=" * 104)

    for res in results:
        print(f"\n[{res['period'].upper()}]")
        ma, ctl = res["ma"], res["control"]
        print(f"  MA: {ma['trades']} trades, exposure {_fmt(ma['average_exposure'], pct=True)}, "
              f"hold {_fmt(ma['average_holding_days'], digits=1)}d")
        print(f"  Random control: mean {ctl['mean_trades']} trades, "
              f"mean exposure {_fmt(ctl['mean_exposure'], pct=True)}"
              + (f", {ctl['trials_with_shortfall']} trials could not place every trade"
                 if ctl["trials_with_shortfall"] else ""))
        print(f"  {'metric':<16}{'MA':>10}{'null p50':>11}{'null p95':>11}"
              f"{'pctile':>9}{'p-value':>10}{'effect':>9}")
        for name, c in res["comparisons"].items():
            pct = c["percentile"]
            pct_text = "n/a" if pct is None else f"{pct * 100:.1f}%"
            print(
                f"  {name:<16}{_fmt(c['observed']):>10}{_fmt(c['null_median']):>11}"
                f"{_fmt(c['null_p95']):>11}{pct_text:>9}"
                f"{_fmt(c['p_value'], digits=4):>10}{_fmt(c['effect_size']):>9}"
            )
        v = res["verdict"]
        print(f"  Above 95th percentile of null: {v['metrics_above_95th'] or 'NONE'}")
        print(f"  Below the null median:         {v['metrics_below_median'] or 'none'}")

    print("\n" + "-" * 104)
    print("READING THIS TABLE")
    print("-" * 104)
    print("  percentile = share of random schedules the MA arm beat.")
    print("  p-value    = one-sided, (1 + #draws >= observed) / (1 + N).")
    print("  A metric only counts as evidence of signal above the 95th percentile.")
    print("  Beating the median is what half of all random schedules also do.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
