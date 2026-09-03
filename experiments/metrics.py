"""V2 — the full performance record.

The backtest engine already computes nine metrics. This module computes the
rest of what V2 asks for -- Calmar, volatility, turnover, holding period,
realised costs, exposure, leverage, tail losses -- and assembles them into
one record.

Two conventions carried in from the rest of the system:

**Unknown is not zero.** A metric that cannot be computed from what
happened returns `None`, never `0.0`. A strategy with no closed trades has
no win rate; reporting 0.0 would claim it lost every trade. This matters
more here than anywhere else in TradingBrain, because a table of performance
figures is exactly the artefact people read without reading the caveats.

**Costs are measured, not assumed.** `realised_cost_bps` comes from summing
the commission and slippage actually charged on fills, not from restating
the configured rate. If the two disagree, the backtest has a bug, and this
is where it shows.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from backtesting.schemas import BacktestResult


def _returns(equity: list[float]) -> list[float]:
    return [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] != 0
    ]


@dataclass
class PerformanceRecord:
    """Every V2 metric, with unknowns represented as None."""

    # --- returns ---
    total_return: float | None = None
    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    max_drawdown: float | None = None

    # --- trades ---
    trade_count: int = 0
    win_rate: float | None = None
    profit_factor: float | None = None
    expectancy: float | None = None
    average_holding_period_days: float | None = None
    turnover: float | None = None

    # --- costs, as actually charged ---
    total_commission: float = 0.0
    total_slippage: float = 0.0
    realised_cost_bps: float | None = None
    cost_drag_on_return: float | None = None

    # --- exposure ---
    average_exposure: float | None = None
    max_exposure: float | None = None
    max_leverage: float | None = None
    time_in_market: float | None = None

    # --- tails ---
    worst_trade: float | None = None
    worst_day: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None
    consecutive_losses: int = 0

    # --- caveats ---
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items()
        }


def _drawdown(equity: list[float]) -> float | None:
    if len(equity) < 2:
        return None
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return round(worst, 6)


def compute(result: BacktestResult) -> PerformanceRecord:
    """Assemble the full record from a completed backtest."""
    record = PerformanceRecord()
    engine = result.metrics
    equity = result.equity_values
    config = result.config

    # The engine's own metrics, passed through rather than recomputed --
    # two implementations of Sharpe that disagree is a bug generator.
    for key in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown",
                "win_rate", "profit_factor", "expectancy"):
        setattr(record, key, engine.get(key))

    record.trade_count = len(result.closed_trades)

    if record.trade_count == 0:
        # Nothing traded. Every trade-derived figure is undefined, not zero.
        record.notes.append(
            "No trades closed: win rate, profit factor, expectancy, holding "
            "period and turnover are undefined rather than zero."
        )
        record.win_rate = None
        record.profit_factor = None
        record.expectancy = None

    if len(equity) < 2:
        record.notes.append(
            f"Only {len(equity)} equity point(s): returns, volatility and "
            "drawdown cannot be computed from a single observation."
        )
        return record

    returns = _returns(equity)

    # --- volatility, annualised ---
    if len(returns) >= 2:
        record.volatility = round(
            statistics.stdev(returns) * math.sqrt(config.periods_per_year), 6
        )

    # --- Calmar: CAGR over max drawdown ---
    dd = record.max_drawdown if record.max_drawdown is not None else _drawdown(equity)
    if record.cagr is not None and dd is not None and dd < 0:
        record.calmar = round(record.cagr / abs(dd), 6)
    elif dd == 0:
        record.notes.append(
            "Calmar is undefined: the equity curve never drew down, so there "
            "is no denominator. This usually means too few observations."
        )

    # --- realised costs, summed from fills ---
    commission = sum(f.commission for f in result.fills)
    slippage = sum(f.slippage for f in result.fills)
    notional = sum(abs(f.quantity * f.price) for f in result.fills)
    record.total_commission = round(commission, 4)
    record.total_slippage = round(slippage, 4)

    if notional > 0:
        record.realised_cost_bps = round((commission + slippage) / notional * 10_000, 4)
        record.turnover = round(notional / config.initial_cash, 4)
    if config.initial_cash > 0:
        record.cost_drag_on_return = round((commission + slippage) / config.initial_cash, 6)

    # --- exposure and leverage ---
    exposures = [
        p.positions_value / p.equity for p in result.equity_curve if p.equity > 0
    ]
    if exposures:
        record.average_exposure = round(sum(exposures) / len(exposures), 6)
        record.max_exposure = round(max(exposures), 6)
        # Leverage above 1.0 means positions exceeded equity. The engine does
        # not support shorting or margin, so anything here is a bug signal.
        record.max_leverage = record.max_exposure
        record.time_in_market = round(
            sum(1 for e in exposures if e > 1e-9) / len(exposures), 6
        )

    # --- tails ---
    if returns:
        record.worst_day = round(min(returns), 6)
        ordered = sorted(returns)
        cut = max(1, int(len(ordered) * 0.05))
        tail = ordered[:cut]
        record.var_95 = round(ordered[cut - 1], 6)
        record.cvar_95 = round(sum(tail) / len(tail), 6)

    pnls = [t.pnl for t in result.closed_trades]
    if pnls:
        record.worst_trade = round(min(pnls), 4)
        streak = worst_streak = 0
        for pnl in pnls:
            streak = streak + 1 if pnl < 0 else 0
            worst_streak = max(worst_streak, streak)
        record.consecutive_losses = worst_streak

    # --- holding period ---
    spans = [
        (t.closed_at - t.opened_at).total_seconds() / 86400
        for t in result.closed_trades
    ]
    if spans:
        record.average_holding_period_days = round(sum(spans) / len(spans), 3)

    # --- sample-size honesty ---
    if 0 < record.trade_count < 30:
        record.notes.append(
            f"Only {record.trade_count} closed trade(s). Win rate, expectancy "
            "and profit factor are descriptive of this sample and carry no "
            "statistical weight."
        )
    if len(equity) < 60:
        record.notes.append(
            f"Only {len(equity)} equity observations. Annualised figures "
            "(CAGR, volatility, Sharpe) extrapolate from a short window."
        )

    return record


def breaches(record: PerformanceRecord, limits) -> list[str]:
    """Risk limits the run actually exceeded.

    A strategy that only performs by breaching its own stated limits has not
    been tested under those limits, so this is reported rather than folded
    into the metrics.
    """
    found: list[str] = []
    over_exposure = (
        record.max_exposure is not None
        and record.max_exposure > limits.max_portfolio_exposure + 1e-9
    )
    if over_exposure and record.max_exposure is not None:
        found.append(
            f"Max exposure {record.max_exposure:.2%} exceeded the "
            f"{limits.max_portfolio_exposure:.2%} portfolio limit."
        )
    if record.max_leverage is not None and record.max_leverage > limits.max_leverage + 1e-9:
        found.append(
            f"Max leverage {record.max_leverage:.2f}x exceeded the "
            f"{limits.max_leverage:.2f}x limit."
        )
    if (
        limits.max_drawdown_stop is not None
        and record.max_drawdown is not None
        and abs(record.max_drawdown) > limits.max_drawdown_stop
    ):
        found.append(
            f"Max drawdown {abs(record.max_drawdown):.2%} exceeded the "
            f"{limits.max_drawdown_stop:.2%} stop."
        )
    return found
