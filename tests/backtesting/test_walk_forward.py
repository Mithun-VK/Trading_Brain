from __future__ import annotations

import datetime as dt

import pytest

from backtesting.engine import BacktestEngine
from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy
from backtesting.walk_forward import WalkForwardValidator, Window
from data.ingestion.schemas import PriceBar

START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _bars(count: int) -> list[PriceBar]:
    bars = []
    price = 100.0
    for i in range(count):
        open_price = price
        price = price * 1.002 if i % 3 else price * 0.999
        bars.append(
            PriceBar(
                ts=START + dt.timedelta(days=i),
                open=open_price,
                high=max(open_price, price) * 1.01,
                low=min(open_price, price) * 0.99,
                close=price,
                volume=1000,
                interval="1d",
                source="test",
            )
        )
    return bars


def _timeline(count: int) -> list[dt.datetime]:
    return [START + dt.timedelta(days=i) for i in range(count)]


def test_split_produces_consecutive_non_overlapping_test_windows() -> None:
    validator = WalkForwardValidator(train_size=10, test_size=5)

    windows = validator.split(_timeline(30))

    assert len(windows) == 4
    for window in windows:
        assert window.train_start < window.train_end < window.test_start <= window.test_end
    # Consecutive pairs, so the two sequences differ in length by design.
    for earlier, later in zip(windows, windows[1:], strict=False):
        assert earlier.test_end < later.test_start


def test_train_window_always_precedes_its_test_window() -> None:
    """The whole point: parameters are chosen before the data they're scored on."""
    validator = WalkForwardValidator(train_size=20, test_size=10)

    for window in validator.split(_timeline(60)):
        assert window.train_end < window.test_start


def test_split_returns_nothing_when_history_is_too_short() -> None:
    validator = WalkForwardValidator(train_size=50, test_size=20)

    assert validator.split(_timeline(30)) == []


def test_step_controls_window_overlap() -> None:
    overlapping = WalkForwardValidator(train_size=10, test_size=5, step=2).split(_timeline(30))
    default = WalkForwardValidator(train_size=10, test_size=5).split(_timeline(30))

    assert len(overlapping) > len(default)


def test_invalid_window_sizes_are_rejected() -> None:
    with pytest.raises(ValueError):
        WalkForwardValidator(train_size=0, test_size=5)
    with pytest.raises(ValueError):
        WalkForwardValidator(train_size=5, test_size=0)


def test_run_scores_only_test_windows() -> None:
    bars = {"AAA": _bars(80)}
    validator = WalkForwardValidator(
        engine=BacktestEngine(), train_size=30, test_size=10
    )

    result = validator.run(BuyAndHoldStrategy(["AAA"]), bars)

    assert len(result.test_results) == len(result.windows) == 5
    for window, test_result in zip(result.windows, result.test_results, strict=True):
        assert test_result.start == window.test_start
        assert test_result.end == window.test_end


def test_combined_metrics_summarize_across_windows() -> None:
    bars = {"AAA": _bars(80)}
    validator = WalkForwardValidator(train_size=30, test_size=10)

    result = validator.run(MovingAverageCrossStrategy(fast=3, slow=8, tickers=["AAA"]), bars)
    metrics = result.combined_metrics

    assert metrics["windows"] == float(len(result.test_results))
    assert "mean_total_return" in metrics
    assert metrics["worst_max_drawdown"] <= 0


def test_on_train_hook_runs_before_each_test_window() -> None:
    bars = {"AAA": _bars(80)}
    seen: list[Window] = []

    def on_train(strategy, window: Window) -> None:
        seen.append(window)

    validator = WalkForwardValidator(train_size=30, test_size=10)
    result = validator.run(BuyAndHoldStrategy(["AAA"]), bars, on_train=on_train)

    assert seen == result.windows


def test_walk_forward_is_deterministic() -> None:
    bars = {"AAA": _bars(80)}
    validator = WalkForwardValidator(train_size=30, test_size=10)

    first = validator.run(MovingAverageCrossStrategy(fast=3, slow=8, tickers=["AAA"]), bars)
    second = validator.run(MovingAverageCrossStrategy(fast=3, slow=8, tickers=["AAA"]), bars)

    assert first.combined_metrics == second.combined_metrics


def test_combined_metrics_of_no_windows_is_empty() -> None:
    bars = {"AAA": _bars(10)}
    validator = WalkForwardValidator(train_size=50, test_size=20)

    result = validator.run(BuyAndHoldStrategy(["AAA"]), bars)

    assert result.combined_metrics == {}
