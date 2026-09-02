"""Position sizing.

Reuses `quant.performance.risk` for the risk-based sizer so a backtest
sizes positions with exactly the maths the live risk layer uses -- one
source of truth (Rule 2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backtesting.schemas import StrategySignal
from quant.performance.risk import position_size


class PositionSizer(ABC):
    @abstractmethod
    def size(
        self, signal: StrategySignal, price: float, equity: float, cash: float
    ) -> float:
        """Quantity to buy. May be 0 -- the engine then records no fill."""


class FixedFractionSizer(PositionSizer):
    """Allocate a fixed fraction of *equity* per entry, scaled by signal
    strength, and never more than available cash allows.
    """

    def __init__(self, fraction: float = 0.1) -> None:
        if not 0 < fraction <= 1:
            raise ValueError("fraction must be in (0, 1]")
        self.fraction = fraction

    def size(self, signal: StrategySignal, price: float, equity: float, cash: float) -> float:
        if price <= 0:
            return 0.0
        budget = min(equity * self.fraction * signal.strength, cash)
        return max(0.0, budget / price)


class FixedQuantitySizer(PositionSizer):
    def __init__(self, quantity: float = 1.0) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.quantity = quantity

    def size(self, signal: StrategySignal, price: float, equity: float, cash: float) -> float:
        affordable = cash / price if price > 0 else 0.0
        return min(self.quantity * signal.strength, affordable)


class RiskBasedSizer(PositionSizer):
    """Size so a stop-out costs a fixed fraction of equity.

    Delegates to `quant.performance.risk.position_size`, the same function
    the trade journal and risk layer use.
    """

    def __init__(self, risk_per_trade: float = 0.01, stop_distance_pct: float = 0.08) -> None:
        if not 0 < risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")
        if stop_distance_pct <= 0:
            raise ValueError("stop_distance_pct must be positive")
        self.risk_per_trade = risk_per_trade
        self.stop_distance_pct = stop_distance_pct

    def size(self, signal: StrategySignal, price: float, equity: float, cash: float) -> float:
        if price <= 0:
            return 0.0
        stop_price = price * (1 - self.stop_distance_pct)
        quantity = position_size(
            account_equity=equity,
            risk_per_trade_pct=self.risk_per_trade * signal.strength,
            entry_price=price,
            stop_price=stop_price,
        )
        affordable = cash / price
        return max(0.0, min(quantity, affordable))
