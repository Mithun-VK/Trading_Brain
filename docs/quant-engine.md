# Quantitative Engine

Every calculation in `quant/` is deterministic pure Python — no LLM call
ever computes a number here (Rule 2). Claude receives the *results*.

## Indicators (`quant/indicators/`)

| Function | Notes |
|---|---|
| `sma(values, period)` | Simple moving average. |
| `ema(values, period)` | Exponential moving average. |
| `rsi(values, period=14)` | Wilder's smoothing. |
| `macd(values, fast=12, slow=26, signal=9)` | Returns `(macd_line, signal_line, histogram)`. |
| `atr(high, low, close, period=14)` | Wilder's smoothing of true range. |
| `bollinger_bands(values, period=20, num_std=2.0)` | Returns `(upper, middle, lower)`. |
| `vwap(high, low, close, volume)` | Cumulative over the series passed in — pass one session's bars for an intraday VWAP. |
| `simple_returns` / `log_returns` | Period-over-period returns. |
| `volatility(returns, annualize=True, periods_per_year=252)` | Stdev, optionally annualized. |
| `max_drawdown(values)` | Largest peak-to-trough decline, as a negative fraction. |

Every function that needs a warm-up window (SMA, EMA, RSI, MACD, ATR,
Bollinger) returns a list the same length as its input, with `None` where
there isn't enough history yet — never a silently wrong early value.

## Risk (`quant/performance/risk.py`)

`position_size`, `risk_amount`, `r_multiple`, `portfolio_exposure`. These
gate what a human is allowed to act on (position sizing, stop placement) —
see [trading-journal.md](trading-journal.md) for how they feed the review
engine.

## Performance (`quant/performance/stats.py`)

`total_return`, `cagr`, `sharpe_ratio`, `sortino_ratio`, `win_rate`,
`profit_factor`, `expectancy`, `average_winner`, `average_loser`. Rule 12
applies to every caller: never present these as a guarantee of future
results, and never claim statistical significance a small sample doesn't
support.

## Testing

`tests/quant/` — every function has hand-verified reference-value tests
(e.g. SMA/EMA against hand-computed windows, ATR/VWAP against a worked
example, R-multiple/position-sizing against known risk math), not just
"runs without crashing" checks.
