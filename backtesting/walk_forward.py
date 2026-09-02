"""Walk-forward validation.

Splits the timeline into consecutive (train, test) windows and reports
**test-window results only**. The train window is where a strategy's
parameters would be chosen; scoring on it would be the same lookahead
mistake as peeking at future bars, one level up.

This module does not fit parameters for you -- it gives you the windows and
runs the out-of-sample segments. `on_train` lets a caller plug in its own
selection step; without one, the split still serves as honest out-of-sample
segmentation.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from backtesting.engine import BacktestEngine
from backtesting.schemas import BacktestResult
from backtesting.strategy import Strategy
from data.ingestion.schemas import PriceBar


@dataclass(frozen=True)
class Window:
    train_start: dt.datetime
    train_end: dt.datetime
    test_start: dt.datetime
    test_end: dt.datetime


@dataclass
class WalkForwardResult:
    windows: list[Window] = field(default_factory=list)
    test_results: list[BacktestResult] = field(default_factory=list)

    @property
    def combined_metrics(self) -> dict[str, float]:
        """Averages across test windows, plus the worst drawdown seen.

        Deliberately not a stitched equity curve: each window restarts from
        the configured initial cash, so chaining them would imply
        compounding that never happened.
        """
        if not self.test_results:
            return {}

        keys = ("total_return", "cagr", "sharpe", "sortino", "win_rate", "expectancy")
        averaged = {
            f"mean_{key}": round(
                sum(r.metrics.get(key, 0.0) for r in self.test_results) / len(self.test_results),
                6,
            )
            for key in keys
        }
        averaged["worst_max_drawdown"] = round(
            min((r.metrics.get("max_drawdown", 0.0) for r in self.test_results), default=0.0), 6
        )
        averaged["windows"] = float(len(self.test_results))
        averaged["total_trades"] = float(
            sum(r.metrics.get("trade_count", 0.0) for r in self.test_results)
        )
        return averaged


class WalkForwardValidator:
    def __init__(
        self,
        engine: BacktestEngine | None = None,
        train_size: int = 120,
        test_size: int = 40,
        step: int | None = None,
    ) -> None:
        if train_size <= 0 or test_size <= 0:
            raise ValueError("train_size and test_size must be positive")
        self.engine = engine or BacktestEngine()
        self.train_size = train_size
        self.test_size = test_size
        # Non-overlapping test windows by default.
        self.step = step if step is not None else test_size

    def split(self, timeline: list[dt.datetime]) -> list[Window]:
        windows: list[Window] = []
        start = 0
        while start + self.train_size + self.test_size <= len(timeline):
            train_slice = timeline[start : start + self.train_size]
            test_slice = timeline[
                start + self.train_size : start + self.train_size + self.test_size
            ]
            windows.append(
                Window(
                    train_start=train_slice[0],
                    train_end=train_slice[-1],
                    test_start=test_slice[0],
                    test_end=test_slice[-1],
                )
            )
            start += self.step
        return windows

    def run(
        self,
        strategy: Strategy,
        bars_by_ticker: dict[str, list[PriceBar]],
        on_train: Callable[[Strategy, Window], None] | None = None,
    ) -> WalkForwardResult:
        timeline = sorted({bar.ts for bars in bars_by_ticker.values() for bar in bars})
        windows = self.split(timeline)

        result = WalkForwardResult(windows=windows)
        for window in windows:
            if on_train is not None:
                on_train(strategy, window)
            # The engine still needs pre-test history for indicator warm-up,
            # so the run starts at train_start but is *scored* from test_start.
            test_result = self.engine.run(
                strategy,
                bars_by_ticker,
                start=window.test_start,
                end=window.test_end,
            )
            result.test_results.append(test_result)

        return result
