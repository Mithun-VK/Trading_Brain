"""V2 — the deterministic baseline.

The control group: TradingBrain with every AI provider disabled. Market
data, validation, quant, signal, risk, backtest, and nothing else.

This is the most important measurement in the whole programme. If the
deterministic strategy has no edge, no amount of reasoning on top will
create one — it will only make the losses more expensively justified. So
the baseline is run first, against a buy-and-hold benchmark, and reported
whatever it says.

Run:  python -m experiments.v2_baseline
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy
from experiments import data, runner
from experiments.config import (
    AIMode,
    CostModel,
    ExperimentConfig,
    Period,
    RiskLimits,
)

UNIVERSE = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "JPM", "JNJ", "XOM", "PG", "WMT")
BENCHMARK = "SPY"

HISTORY_START = dt.date(2016, 1, 1)
HISTORY_END = dt.date(2026, 9, 1)

# Chronological split. Train ends before validation begins, validation before
# test -- and the test window has never been looked at while choosing
# anything, which is the only thing that makes it out-of-sample.
TRAIN = Period("train", dt.date(2016, 1, 1), dt.date(2021, 1, 1))
VALIDATION = Period("validation", dt.date(2021, 1, 1), dt.date(2023, 1, 1))
TEST = Period("test", dt.date(2023, 1, 1), dt.date(2026, 9, 1))

FROZEN_COMMIT = "25f6746"


def config(
    strategy: str,
    params: dict[str, float] | None = None,
    *,
    position_size_pct: float = 0.10,
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="V2-BASELINE",
        strategy=strategy,
        strategy_version="1.0",
        frozen_at_commit=FROZEN_COMMIT,
        description="Deterministic control group: all AI providers disabled.",
        universe=UNIVERSE,
        timeframe="1d",
        historical_period=Period("history", HISTORY_START, HISTORY_END),
        train=TRAIN,
        validation=VALIDATION,
        test=TEST,
        initial_cash=100_000.0,
        costs=CostModel(commission_bps=5.0, slippage_bps=5.0),
        risk=RiskLimits(
            max_position_pct=0.20,
            max_portfolio_exposure=1.00,
            max_leverage=1.00,
            max_positions=10,
        ),
        position_sizing="fixed_fraction",
        position_size_pct=position_size_pct,
        ai_mode=AIMode.DISABLED,
        random_seed=20260901,
        strategy_params=params or {},
    )


def _period_bars(bars, period: Period):
    """Bars whose timestamp falls inside the period. Warm-up is handled by
    the strategy needing `slow` bars before it signals, and those come from
    inside the window -- never borrowed from after it."""
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


def main() -> int:
    print("Loading real market data (Yahoo)...")
    universe_bars = data.align(
        data.load([*UNIVERSE, BENCHMARK], HISTORY_START, HISTORY_END)
    )
    if not universe_bars:
        print("No data loaded. Cannot run a baseline over nothing.")
        return 1

    coverage = data.coverage(universe_bars)
    print(f"  {coverage['tickers']} tickers, {coverage['bars']} bars, "
          f"{coverage['first']} to {coverage['last']}\n")

    strategy_bars = {t: b for t, b in universe_bars.items() if t in UNIVERSE}
    benchmark_bars = {BENCHMARK: universe_bars[BENCHMARK]} if BENCHMARK in universe_bars else {}

    runs = []
    for period in (TRAIN, VALIDATION, TEST):
        window = _period_bars(strategy_bars, period)
        if not any(window.values()):
            continue

        strategy_run = runner.run(
            config("ma_cross", {"fast": 20, "slow": 50}),
            MovingAverageCrossStrategy(fast=20, slow=50, tickers=list(UNIVERSE)),
            window,
            provider="yahoo",
            period=period.name,
        )
        runs.append(("ma_cross", period.name, strategy_run))

        if benchmark_bars:
            bench_window = _period_bars(benchmark_bars, period)
            bench_run = runner.run(
                # Fully invested: "buy and hold SPY" means 100% SPY, not 10%
                # SPY and 90% cash. The strategy's own exposure is reported
                # alongside so the comparison is legible rather than implied.
                config("buy_and_hold_spy", position_size_pct=1.0),
                BuyAndHoldStrategy(tickers=[BENCHMARK]),
                bench_window,
                provider="yahoo",
                period=period.name,
            )
            runs.append(("spy_buy_hold", period.name, bench_run))

    _report(runs)
    return 0


def _fmt(value: float | None, *, pct: bool = False, digits: int = 2) -> str:
    """Unknown renders as a word, never as a number."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%" if pct else f"{value:.{digits}f}"


def _report(runs) -> None:
    print("=" * 100)
    print("V2 DETERMINISTIC BASELINE — all AI disabled")
    print("=" * 100)

    header = f"{'arm':<16}{'period':<12}{'CAGR':>9}{'Sharpe':>9}{'Sortino':>9}" \
             f"{'MaxDD':>9}{'Calmar':>9}{'Vol':>9}{'Win%':>8}{'Trades':>8}"
    print(header)
    print("-" * 100)

    for name, period, run in runs:
        p = run.performance
        print(
            f"{name:<16}{period:<12}"
            f"{_fmt(p.cagr, pct=True):>9}{_fmt(p.sharpe):>9}{_fmt(p.sortino):>9}"
            f"{_fmt(p.max_drawdown, pct=True):>9}{_fmt(p.calmar):>9}"
            f"{_fmt(p.volatility, pct=True):>9}{_fmt(p.win_rate, pct=True, digits=0):>8}"
            f"{p.trade_count:>8}"
        )

    print("-" * 100)
    certified = [r for _, _, r in runs if r.certified]
    print(f"Certified runs: {len(certified)}/{len(runs)}")
    if runs:
        first = runs[0][2]
        print(f"Data: {first.provenance.quality} via {first.provenance.provider} "
              f"(snapshot {first.provenance.snapshot_id})")
        print(f"Config fingerprint: {first.config_fingerprint}")

    print("\nCosts and exposure (test period):")
    for name, period, run in runs:
        if period != "test":
            continue
        p = run.performance
        print(f"  {name}: commission {p.total_commission:.2f}, slippage {p.total_slippage:.2f}, "
              f"realised {_fmt(p.realised_cost_bps)}bp, turnover {_fmt(p.turnover)}x, "
              f"avg exposure {_fmt(p.average_exposure, pct=True)}, "
              f"hold {_fmt(p.average_holding_period_days, digits=1)}d")

    print("\nTails (test period):")
    for name, period, run in runs:
        if period != "test":
            continue
        p = run.performance
        print(f"  {name}: worst day {_fmt(p.worst_day, pct=True)}, "
              f"VaR95 {_fmt(p.var_95, pct=True)}, CVaR95 {_fmt(p.cvar_95, pct=True)}, "
              f"worst trade {_fmt(p.worst_trade)}, max losing streak {p.consecutive_losses}")

    notes = {n for _, _, r in runs for n in r.performance.notes}
    if notes:
        print("\nCaveats:")
        for note in sorted(notes):
            print(f"  - {note}")

    breaches = [(n, p, b) for n, p, r in runs for b in r.limit_breaches]
    if breaches:
        print("\nRisk limit breaches:")
        for name, period, breach in breaches:
            print(f"  - {name}/{period}: {breach}")

    payload = [
        {"arm": n, "period": p, **r.headline(), "metrics": r.performance.to_dict()}
        for n, p, r in runs
    ]
    out = "experiments/results_v2_baseline.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, default=str)
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    sys.exit(main())
