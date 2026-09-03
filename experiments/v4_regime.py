"""V4 — regime decomposition of the frozen MA 20/50 baseline.

Diagnostic only. No parameters are tuned, no strategy is changed, and no
result here is an argument for making the Sharpe higher. The question is
narrow: *when* does this strategy work, *when* does it fail, and is the
difference explained by anything identifiable?

The V2 result — strong in train, negative in validation, strong in test —
is exactly the shape where optimising parameters would manufacture an
overfit. So this phase diagnoses before anything is improved.

Run:  python -m experiments.v4_regime
"""

from __future__ import annotations

import json
import sys

from backtesting.strategy import MovingAverageCrossStrategy
from experiments import data, regimes, runner, trade_analysis
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
from experiments.v4_questions import answer_all


def _window(bars, period: Period):
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


def main() -> int:
    print("Loading market data (Yahoo, cached)...")
    all_bars = data.align(data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END))
    if BENCHMARK not in all_bars:
        print(f"No {BENCHMARK} data: market regime cannot be labelled.")
        return 1

    strategy_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}

    # Regime labels are computed over the FULL history in one causal forward
    # pass, then looked up per trade. Labelling each period separately would
    # restart the drawdown tracker at every window boundary and erase the
    # crisis states that straddle one.
    print("Labelling market regime (SPY, causal forward pass)...")
    market_labels = regimes.label_series(all_bars[BENCHMARK])
    print(f"  {len(market_labels)} bars labelled")
    print(f"  distribution: {regimes.distribution(market_labels)}\n")

    periods = {}
    for period in (TRAIN, VALIDATION, TEST):
        window = _window(strategy_bars, period)
        run = runner.run(
            config("ma_cross", {"fast": 20, "slow": 50}),
            MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(UNIVERSE)),
            window,
            provider="yahoo",
            period=period.name,
        )
        assert run.result is not None
        records = trade_analysis.enrich(run.result, window, market_labels=market_labels)
        period_labels = [
            label for label in market_labels if period.contains(label.date)
        ]
        periods[period.name] = {
            "run": run,
            "records": records,
            "labels": period_labels,
        }
        print(f"{period.name}: {len(records)} closed trades")

    print()
    findings = answer_all(periods, all_bars, market_labels)
    _report(periods, market_labels, findings)
    return 0


def _fmt(value, *, pct=False, digits=2) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%" if pct else f"{value:.{digits}f}"


def _report(periods, market_labels, findings) -> None:
    print("=" * 104)
    print("V4 REGIME DECOMPOSITION — MA 20/50, frozen baseline, diagnostic only")
    print("=" * 104)

    all_records = [r for p in periods.values() for r in p["records"]]

    # --- regime distribution per period ---
    print("\nMARKET REGIME COMPOSITION (share of trading days)")
    print("-" * 104)
    for name, payload in periods.items():
        dist = regimes.distribution(payload["labels"])
        total = sum(dist.values()) or 1
        parts = ", ".join(f"{k} {v/total:.0%}" for k, v in dist.items())
        print(f"  {name:<12} {parts}")

    # --- per-regime performance, all periods pooled ---
    print("\nPERFORMANCE BY ENTRY REGIME (all periods pooled)")
    print("-" * 104)
    header = (f"{'regime':<22}{'trades':>8}{'total P&L':>12}{'win%':>8}"
              f"{'avg ret':>10}{'PF':>8}{'avg MAE':>10}{'avg MFE':>10}{'sig?':>7}")
    print(header)
    for stat in trade_analysis.by_regime(all_records):
        print(
            f"{stat.regime:<22}{stat.trades:>8}{stat.total_pnl:>12.2f}"
            f"{_fmt(stat.win_rate, pct=True, digits=0):>8}"
            f"{_fmt(stat.average_return, pct=True):>10}"
            f"{_fmt(stat.profit_factor):>8}"
            f"{_fmt(stat.average_mae, pct=True):>10}"
            f"{_fmt(stat.average_mfe, pct=True):>10}"
            f"{('yes' if stat.is_significant else 'no'):>7}"
        )

    # --- per-regime, per-period ---
    print("\nPERFORMANCE BY ENTRY REGIME, PER PERIOD")
    print("-" * 104)
    for name, payload in periods.items():
        print(f"  [{name}]")
        stats = trade_analysis.by_regime(payload["records"])
        if not stats:
            print("    no closed trades")
            continue
        for stat in stats:
            print(
                f"    {stat.regime:<20}{stat.trades:>6} trades"
                f"{stat.total_pnl:>12.2f}"
                f"{_fmt(stat.average_return, pct=True):>10} avg"
                f"{_fmt(stat.win_rate, pct=True, digits=0):>8} win"
                f"{'' if stat.is_significant else '   (small sample)'}"
            )

    # --- volatility regime ---
    print("\nPERFORMANCE BY VOLATILITY REGIME AT ENTRY")
    print("-" * 104)
    for stat in trade_analysis.by_regime(all_records, key="entry_volatility_regime"):
        print(
            f"  {stat.regime:<20}{stat.trades:>6} trades"
            f"{stat.total_pnl:>12.2f}{_fmt(stat.average_return, pct=True):>10} avg"
            f"{_fmt(stat.win_rate, pct=True, digits=0):>8} win"
            f"{'' if stat.is_significant else '   (small sample)'}"
        )

    # --- concentration ---
    print("\nP&L CONCENTRATION (all periods)")
    print("-" * 104)
    conc = trade_analysis.concentration(all_records)
    for key in ("trades", "total_pnl", "top_1_share_of_pnl", "top_5_share_of_pnl",
                "top_10_share_of_pnl", "winners", "losers", "largest_win", "largest_loss"):
        print(f"  {key:<22} {conc.get(key)}")

    # --- per ticker ---
    print("\nBY TICKER (all periods)")
    print("-" * 104)
    for ticker, stat in trade_analysis.by_ticker(all_records).items():
        print(f"  {ticker:<8}{stat['trades']:>5} trades{stat['total_pnl']:>12.2f}"
              f"{stat['average_return']*100:>9.2f}% avg{stat['win_rate']*100:>8.0f}% win")

    # --- the ten questions ---
    print("\n" + "=" * 104)
    print("V4 QUESTIONS")
    print("=" * 104)
    for i, (question, answer) in enumerate(findings.items(), 1):
        print(f"\n{i}. {question}")
        for line in answer["answer"]:
            print(f"   {line}")
        if answer.get("caveat"):
            print(f"   CAVEAT: {answer['caveat']}")

    payload = {
        "regime_distribution_all": regimes.distribution(market_labels),
        "by_regime_pooled": [s.to_dict() for s in trade_analysis.by_regime(all_records)],
        "by_volatility": [
            s.to_dict()
            for s in trade_analysis.by_regime(all_records, key="entry_volatility_regime")
        ],
        "by_period": {
            name: [s.to_dict() for s in trade_analysis.by_regime(p["records"])]
            for name, p in periods.items()
        },
        "concentration": conc,
        "by_ticker": trade_analysis.by_ticker(all_records),
        "trades": [r.to_dict() for r in all_records],
        "questions": findings,
    }
    out = "experiments/results_v4_regime.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    sys.exit(main())
