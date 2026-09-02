"""Strategy contract.

A strategy is a pure function of the past: it receives a `MarketView`
already sliced to the current bar and returns signals. It gets no session,
no clock, and no provider -- which is what makes a backtest reproducible
and lookahead-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backtesting.market_view import MarketView
from backtesting.schemas import SignalAction, StrategySignal
from quant.indicators.moving_average import sma


class Strategy(ABC):
    name: str = "strategy"

    def on_start(self) -> None:  # noqa: B027 -- optional hook, deliberately not abstract
        """Reset any internal state so one instance can be reused across
        runs/windows deterministically.

        Intentionally concrete-and-empty: stateless strategies shouldn't be
        forced to implement a no-op.
        """

    @abstractmethod
    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        """Return signals given everything observable up to now."""


class BuyAndHoldStrategy(Strategy):
    """Buys each ticker once, on its first available bar, then holds.

    Useful as a benchmark and as a fixture that exercises the engine
    end-to-end without depending on indicator behaviour.
    """

    name = "buy_and_hold"

    def __init__(self, tickers: list[str] | None = None) -> None:
        self.tickers = tickers
        self._bought: set[str] = set()

    def on_start(self) -> None:
        self._bought = set()

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        universe = self.tickers if self.tickers is not None else view.tickers
        signals = []
        for ticker in universe:
            if ticker in self._bought or not view.is_current(ticker):
                continue
            self._bought.add(ticker)
            signals.append(
                StrategySignal(
                    ticker=ticker,
                    action=SignalAction.BUY,
                    reason="initial entry",
                )
            )
        return signals


class MovingAverageCrossStrategy(Strategy):
    """Long while the fast SMA is above the slow SMA, flat otherwise.

    Uses `quant.indicators` rather than a private implementation, so the
    backtest measures the same maths the live analysis path uses.
    """

    name = "ma_cross"

    def __init__(self, fast: int = 10, slow: int = 30, tickers: list[str] | None = None) -> None:
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast = fast
        self.slow = slow
        self.tickers = tickers
        self._long: set[str] = set()

    def on_start(self) -> None:
        self._long = set()

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        universe = self.tickers if self.tickers is not None else view.tickers
        signals: list[StrategySignal] = []

        for ticker in universe:
            if not view.is_current(ticker):
                continue
            closes = view.closes(ticker)
            if len(closes) < self.slow:
                continue

            fast_value = sma(closes, self.fast)[-1]
            slow_value = sma(closes, self.slow)[-1]
            if fast_value is None or slow_value is None:
                continue

            is_long = ticker in self._long
            if fast_value > slow_value and not is_long:
                self._long.add(ticker)
                signals.append(
                    StrategySignal(
                        ticker=ticker,
                        action=SignalAction.BUY,
                        reason=f"SMA{self.fast} crossed above SMA{self.slow}",
                    )
                )
            elif fast_value <= slow_value and is_long:
                self._long.discard(ticker)
                signals.append(
                    StrategySignal(
                        ticker=ticker,
                        action=SignalAction.SELL,
                        reason=f"SMA{self.fast} crossed below SMA{self.slow}",
                    )
                )

        return signals
