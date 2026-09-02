# Backtesting Framework

`backtesting/`. Measures a strategy against history — deterministically,
and without letting it see the future.

```text
market_view.py   MarketView      anti-lookahead data access
strategy.py      Strategy        the contract + two reference strategies
sizing.py        PositionSizer   fixed-fraction / fixed-quantity / risk-based
engine.py        BacktestEngine  the simulation loop
walk_forward.py  WalkForwardValidator
schemas.py       config, signals, fills, trades, results
```

## Anti-lookahead is structural, not documented

The most dangerous backtest bug is a strategy seeing data it couldn't have
had. Two mechanisms prevent it here:

**1. The strategy never receives the price series.** It gets a `MarketView`
that has already been sliced to the current bar. There is no accessor that
reaches past it — future data isn't forbidden, it's *absent*. Even
`view.bars(ticker, lookback=100_000)` cannot conjure a bar that hasn't
happened.

**2. Signals fill on the *next* bar's open.**

```text
step i:  1. fill orders queued at step i-1, at bar[i].OPEN + slippage
         2. build MarketView sliced through bar[i].CLOSE
         3. ask the strategy for signals
         4. queue resulting orders for step i+1
         5. mark to market at bar[i].CLOSE
```

Filling at the same close a signal was computed from would mean trading at a
price the instant you first observe it. A signal on the final bar therefore
*cannot* fill and is recorded in `result.unfilled` rather than quietly
executed.

Both properties are asserted directly: `test_strategy_only_ever_sees_past_and_present_bars`
checks the strategy saw exactly `closes[:i+1]` on every bar, and
`test_orders_fill_at_the_next_bar_open_not_the_signal_bar_close` pins the
fill price to the next open.

## Reproducibility

No wall clock, no randomness, sorted iteration everywhere. The same inputs
produce identical metrics, equity curve, and fills — asserted by
`test_backtests_are_deterministic`. `Strategy.on_start()` resets internal
state so **reusing one instance across runs is also deterministic**, which
matters for walk-forward.

## Shared accounting

Position accounting delegates to `quant.performance.portfolio` — the same
`apply_buy`/`apply_sell` the paper portfolio uses. A backtest and a paper
trade of the same sequence therefore produce the same average cost and
realized P&L by construction, rather than by two implementations happening
to agree. Sizing likewise reuses `quant.performance.risk.position_size`.

## Costs

`BacktestConfig(commission_bps=5, slippage_bps=5)`. Slippage is always
adverse — buys pay up, sells receive less. Commission is charged on
notional and capitalized through the shared accounting functions. Cash is
never allowed to go negative; an order too large for the balance is trimmed
or refused, and the refusal is recorded.

## Metrics

`total_return`, `cagr`, `sharpe`, `sortino`, `max_drawdown`, `win_rate`,
`profit_factor`, `expectancy`, `trade_count` — all computed by the existing
`quant/performance/stats.py` and `quant/indicators/returns.py` functions,
not reimplemented.

## Walk-forward validation

`WalkForwardValidator(train_size, test_size, step)` splits the timeline
into consecutive `(train, test)` windows and **scores test windows only**.
Scoring on the training window would be the same lookahead mistake one
level up — choosing parameters using data you then grade yourself on.

`combined_metrics` averages across test windows and reports the worst
drawdown. It deliberately does **not** stitch the windows into one equity
curve: each window restarts from the configured initial cash, so chaining
them would imply compounding that never happened.

The validator doesn't fit parameters for you — pass an `on_train` callback
to plug in your own selection step. Without one, the split still gives
honest out-of-sample segmentation.

## Naming: this is not the Signal Engine

`SignalAction.BUY/SELL` here are **simulation instructions**, not
recommendations. The Phase 19 `SignalEngine` that produces human-facing
output has no BUY/SELL categories at all (WATCH / RESEARCH / ACCUMULATE /
REDUCE / EXIT_REVIEW / THESIS_REVIEW). Simulating a fill to measure a
strategy is not the same thing as telling someone to trade (Rules 7/8), and
nothing in this package touches a broker.

## Usage

```python
from backtesting import BacktestEngine, BacktestConfig, MovingAverageCrossStrategy
from backtesting.sizing import FixedFractionSizer

engine = BacktestEngine(BacktestConfig(initial_cash=100_000), FixedFractionSizer(0.2))
result = engine.run(MovingAverageCrossStrategy(fast=20, slow=50), {"RELIANCE": bars})
print(result.metrics, result.final_equity)
```

## Testing

`tests/backtesting/` — 32 tests covering lookahead prevention, the
next-open fill rule, determinism (including instance reuse), cost effects,
cash constraints, short rejection, multi-asset and weekly bars, every
metric, all three sizers, and walk-forward window construction/ordering.
