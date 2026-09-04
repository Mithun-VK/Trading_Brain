"""Regression test for the `MarketView.at()` performance fix.

The change replaced a full linear rescan of each ticker's history on every
timestep with a `bisect_right` cutoff, on the assumption that
`bars_by_ticker` is already sorted ascending -- which the engine guarantees
by sorting once before the timeline loop begins. This test pins the
behavioural contract directly: given sorted input, the two implementations
must select exactly the same bars in exactly the same order.

This lives outside `tests/backtesting/` deliberately: it exists to protect
a performance change made to support the experiments framework's Monte
Carlo sweeps, not to describe `MarketView`'s design on its own terms.
"""

from __future__ import annotations

import datetime as dt

from backtesting.market_view import MarketView
from data.ingestion.schemas import PriceBar

START = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _bars(n: int) -> list[PriceBar]:
    return [
        PriceBar(
            ts=START + dt.timedelta(days=i),
            open=100 + i, high=101 + i, low=99 + i, close=100 + i,
            volume=1_000, interval="1d", source="test",
        )
        for i in range(n)
    ]


def _linear_reference(bars: list[PriceBar], timestamp: dt.datetime) -> list[PriceBar]:
    """The original implementation, kept here only as the ground truth this
    test checks the optimized one against."""
    return [bar for bar in bars if bar.ts <= timestamp]


def test_bisect_slice_matches_the_linear_scan_at_every_cutoff() -> None:
    bars = {"AAPL": _bars(120)}

    for i in range(0, 120, 7):
        cutoff = START + dt.timedelta(days=i)
        view = MarketView.at(bars, cutoff)
        expected = _linear_reference(bars["AAPL"], cutoff)

        actual = view.bars("AAPL") if expected else []
        assert actual == expected, f"mismatch at cutoff day {i}"


def test_a_timestamp_before_all_bars_yields_an_empty_view() -> None:
    bars = {"AAPL": _bars(30)}

    view = MarketView.at(bars, START - dt.timedelta(days=1))

    assert not view.has_data("AAPL")


def test_a_timestamp_after_all_bars_includes_everything() -> None:
    bars = {"AAPL": _bars(30)}

    view = MarketView.at(bars, START + dt.timedelta(days=1000))

    assert len(view.bars("AAPL")) == 30


def test_a_timestamp_exactly_on_a_bar_includes_that_bar() -> None:
    """The cutoff is `<=`, not `<` -- a strategy sees the bar it is standing
    on, not just the ones strictly before it."""
    bars = {"AAPL": _bars(10)}
    on_bar = bars["AAPL"][5].ts

    view = MarketView.at(bars, on_bar)

    assert view.current_bar("AAPL") is not None
    assert view.current_bar("AAPL").ts == on_bar  # type: ignore[union-attr]


def test_multiple_tickers_are_sliced_independently() -> None:
    bars = {"AAPL": _bars(50), "MSFT": _bars(30)}

    view = MarketView.at(bars, START + dt.timedelta(days=40))

    assert len(view.bars("AAPL")) == 41
    assert len(view.bars("MSFT")) == 30  # MSFT ran out of history first


def test_an_empty_ticker_series_is_dropped_not_kept_as_empty() -> None:
    bars = {"AAPL": _bars(10), "MSFT": []}

    view = MarketView.at(bars, START + dt.timedelta(days=5))

    assert "MSFT" not in view.tickers
    assert "AAPL" in view.tickers
