"""Backtest value types.

Naming note: `SignalAction` here is a **simulation instruction**, not a
recommendation to a human. It is deliberately distinct from the Phase 19
`SignalEngine`, whose categories (WATCH / RESEARCH / ACCUMULATE / ...)
never include BUY or SELL. A backtest must be able to simulate fills to
measure a strategy; that is not the same thing as telling you to trade
(Rules 7/8).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class StrategySignal:
    ticker: str
    action: SignalAction
    # 0..1. Sizers scale by this; on a SELL it is the fraction of the
    # position to close (1.0 = flat).
    strength: float = 1.0
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    ticker: str
    action: SignalAction
    quantity: float
    price: float
    commission: float
    slippage: float
    timestamp: dt.datetime
    realized_pnl: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ClosedTrade:
    """A round trip, from first entry to flat. Produced by the engine so
    trade-level statistics (win rate, expectancy) have something to count.
    """

    ticker: str
    quantity: float
    entry_price: float
    exit_price: float
    opened_at: dt.datetime
    closed_at: dt.datetime
    pnl: float
    return_pct: float


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    # Costs in basis points of notional (10 bps = 0.10%).
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    # Trading days per year, for annualizing Sharpe/Sortino/CAGR.
    periods_per_year: int = 252
    risk_free_rate: float = 0.0

    def commission_on(self, notional: float) -> float:
        return abs(notional) * self.commission_bps / 10_000

    def slippage_price(self, price: float, action: SignalAction) -> float:
        """Fills are adverse: buys pay up, sells receive less."""
        adjustment = price * self.slippage_bps / 10_000
        if action is SignalAction.BUY:
            return price + adjustment
        if action is SignalAction.SELL:
            return max(price - adjustment, 1e-9)
        return price


@dataclass
class EquityPoint:
    timestamp: dt.datetime
    cash: float
    positions_value: float
    equity: float


@dataclass
class BacktestResult:
    config: BacktestConfig
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    equity_curve: list[EquityPoint] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    # Orders that could not fill (no subsequent bar, or insufficient cash).
    unfilled: list[dict] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.config.initial_cash

    @property
    def equity_values(self) -> list[float]:
        return [point.equity for point in self.equity_curve]
