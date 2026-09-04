"""Experiment 2 — NVDA concentration and leave-one-ticker-out.

V4 found NVDA supplied ~45% of total P&L. This experiment asks the question
directly: does the strategy's result survive removing its largest
contributor, and is that sensitivity specific to NVDA or general?

Not a universe-selection exercise. Nothing here chooses a "better" universe
-- every leave-one-out run uses the same frozen strategy and the same nine
or ten remaining tickers exactly as V2/V4 defined them, minus one.

Run:  python -m experiments.e2_concentration
"""

from __future__ import annotations

import json
import sys

from backtesting.strategy import MovingAverageCrossStrategy
from experiments import data, runner, trade_analysis
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

PERIODS = {"train": TRAIN, "validation": VALIDATION, "test": TEST}


def _window(bars, period: Period):
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


def _run_universe(universe: tuple[str, ...], strategy_bars: dict, period: Period):
    window = {t: strategy_bars[t] for t in universe if t in strategy_bars}
    window = _window(window, period)
    run = runner.run(
        config("ma_cross", {"fast": 20, "slow": 50}),
        MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(universe)),
        window, provider="yahoo", period=period.name,
    )
    return run, window


def main() -> int:
    print("Loading market data (Yahoo, cached)...")
    all_bars = data.align(data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END))
    strategy_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}
    full = Period("full", HISTORY_START, HISTORY_END)

    # --- A: full universe, all periods pooled, for the concentration figures ---
    print("\nA. Full universe (baseline reference)")
    full_run, full_window = _run_universe(UNIVERSE, strategy_bars, full)
    assert full_run.result is not None
    full_records = trade_analysis.enrich(full_run.result, full_window)
    conc = trade_analysis.concentration(full_records)
    by_ticker = trade_analysis.by_ticker(full_records)
    print(f"   {full_run.performance.trade_count} trades, "
          f"total P&L {conc['total_pnl']}")

    # --- B: exclude NVDA, every period ---
    print("\nB. Excluding NVDA")
    without_nvda = tuple(t for t in UNIVERSE if t != "NVDA")
    b_results = {}
    for name, period in {**PERIODS, "full": full}.items():
        with_run, _ = _run_universe(UNIVERSE, strategy_bars, period)
        without_run, _ = _run_universe(without_nvda, strategy_bars, period)
        b_results[name] = {"with_nvda": with_run, "without_nvda": without_run}
        print(f"   [{name}] with: CAGR {with_run.performance.cagr}, "
              f"Sharpe {with_run.performance.sharpe} | "
              f"without: CAGR {without_run.performance.cagr}, "
              f"Sharpe {without_run.performance.sharpe}")

    # --- C: leave-one-out, every ticker, full period ---
    print("\nC. Leave-one-ticker-out (full period)")
    loo_results = {}
    for excluded in UNIVERSE:
        remaining = tuple(t for t in UNIVERSE if t != excluded)
        run, _ = _run_universe(remaining, strategy_bars, full)
        loo_results[excluded] = run
        print(f"   without {excluded:<6}: CAGR {run.performance.cagr}, "
              f"Sharpe {run.performance.sharpe}, "
              f"P&L change vs full n/a")

    _report(full_run, conc, by_ticker, b_results, loo_results, without_nvda)

    payload = {
        "full_universe": {
            "trade_count": full_run.performance.trade_count,
            "concentration": conc,
            "by_ticker": by_ticker,
            "metrics": full_run.performance.to_dict(),
        },
        "exclude_nvda_by_period": {
            name: {
                "with_nvda": r["with_nvda"].performance.to_dict(),
                "without_nvda": r["without_nvda"].performance.to_dict(),
            }
            for name, r in b_results.items()
        },
        "leave_one_out": {
            ticker: run.performance.to_dict() for ticker, run in loo_results.items()
        },
    }
    out = "experiments/results_e2_concentration.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWritten: {out}")
    return 0


def _fmt(v, pct=False, digits=2) -> str:
    if v is None:
        return "n/a"
    return f"{v*100:.{digits}f}%" if pct else f"{v:.{digits}f}"


def _report(full_run, conc, by_ticker, b_results, loo_results, without_nvda) -> None:
    print("\n" + "=" * 104)
    print("EXPERIMENT 2 — NVDA CONCENTRATION AND LEAVE-ONE-TICKER-OUT")
    print("=" * 104)

    print("\nC1. P&L CONCENTRATION (full period, full universe)")
    for key in ("trades", "total_pnl", "top_1_share_of_pnl", "top_5_share_of_pnl",
                "top_10_share_of_pnl", "winners", "losers"):
        print(f"  {key:<24} {conc.get(key)}")

    total = sum(s["total_pnl"] for s in by_ticker.values()) or 1
    print("\nC2. P&L SHARE BY TICKER")
    for ticker, s in sorted(by_ticker.items(), key=lambda kv: -kv[1]["total_pnl"]):
        print(f"  {ticker:<8}{s['total_pnl']:>12.2f}  "
              f"({s['total_pnl']/total*100:>5.1f}% of total)  "
              f"{s['trades']:>4} trades  win {s['win_rate']*100:.0f}%")

    print("\nB. EXCLUDING NVDA, BY PERIOD")
    header = f"{'period':<12}{'variant':<14}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'trades':>8}"
    print(header)
    for name, r in b_results.items():
        for variant, run in (("with NVDA", r["with_nvda"]), ("without NVDA", r["without_nvda"])):
            p = run.performance
            print(f"{name:<12}{variant:<14}{_fmt(p.cagr, pct=True):>9}"
                  f"{_fmt(p.sharpe):>9}{_fmt(p.max_drawdown, pct=True):>9}"
                  f"{p.trade_count:>8}")

    full_without = b_results["full"]["without_nvda"].performance
    full_with = b_results["full"]["with_nvda"].performance
    print(f"\n  Full period Sharpe: with NVDA {_fmt(full_with.sharpe)}, "
          f"without {_fmt(full_without.sharpe)}")
    survives = full_without.sharpe is not None and full_without.sharpe > 0.3
    verdict = (
        "SURVIVES without NVDA (Sharpe remains > 0.3)"
        if survives else "DOES NOT SURVIVE without NVDA (Sharpe collapses)"
    )
    print(f"  Verdict: {verdict}")

    print("\nC. LEAVE-ONE-TICKER-OUT (full period)")
    print(f"  {'excluded':<10}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'P&L':>13}{'trades':>8}")
    baseline_sharpe = full_run.performance.sharpe
    for ticker in loo_results:
        p = loo_results[ticker].performance
        flag = ""
        if p.sharpe is not None and baseline_sharpe is not None:
            drop = baseline_sharpe - p.sharpe
            if drop > 0.3:
                flag = "  <-- large Sharpe drop when removed"
        pnl = sum(
            t["total_pnl"] for name, t in by_ticker.items() if name != ticker
        )
        print(f"  {ticker:<10}{_fmt(p.cagr, pct=True):>9}{_fmt(p.sharpe):>9}"
              f"{_fmt(p.max_drawdown, pct=True):>9}{pnl:>13.2f}{p.trade_count:>8}{flag}")


if __name__ == "__main__":
    sys.exit(main())
