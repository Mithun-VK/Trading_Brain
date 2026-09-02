"""Deterministic, lookahead-free backtesting.

Simulating fills is how a strategy gets measured; it is not a
recommendation to trade. Nothing in this package touches a broker, and the
Phase 19 SignalEngine that produces human-facing output deliberately has no
BUY/SELL categories at all (Rules 7/8).
"""

from backtesting.engine import BacktestEngine
from backtesting.market_view import MarketView
from backtesting.schemas import (
    BacktestConfig,
    BacktestResult,
    ClosedTrade,
    EquityPoint,
    Fill,
    SignalAction,
    StrategySignal,
)
from backtesting.sizing import (
    FixedFractionSizer,
    FixedQuantitySizer,
    PositionSizer,
    RiskBasedSizer,
)
from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy, Strategy
from backtesting.walk_forward import WalkForwardResult, WalkForwardValidator, Window

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "ClosedTrade",
    "EquityPoint",
    "Fill",
    "MarketView",
    "SignalAction",
    "StrategySignal",
    "Strategy",
    "BuyAndHoldStrategy",
    "MovingAverageCrossStrategy",
    "PositionSizer",
    "FixedFractionSizer",
    "FixedQuantitySizer",
    "RiskBasedSizer",
    "WalkForwardValidator",
    "WalkForwardResult",
    "Window",
]
