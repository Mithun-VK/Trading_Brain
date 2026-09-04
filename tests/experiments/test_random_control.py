"""Random-entry control (Experiment 1).

The tests that matter most here are the ones that would catch the control
cheating: seeing a future price, overlapping two positions in the same
name, or drifting from what it claims to be matched to. A Monte Carlo
comparison is only as trustworthy as the thing being compared against.
"""

from __future__ import annotations

import datetime as dt
import random

from data.ingestion.schemas import PriceBar
from experiments.random_control import (
    MatchTarget,
    PlannedTrade,
    RandomEntryStrategy,
    build_plan,
    plan_shortfall,
    target_from,
)

START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _bars(n: int, ticker: str = "AAA") -> list[PriceBar]:
    return [
        PriceBar(
            ts=START + dt.timedelta(days=i),
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=1_000, interval="1d", source="vendor",
        )
        for i in range(n)
    ]


class _FakeTrade:
    """Duck-types the fields `target_from` reads from a TradeRecord."""

    def __init__(self, ticker: str, entry: dt.date, exit_: dt.date) -> None:
        self.ticker = ticker
        self.entry_date = entry
        self.exit_date = exit_


# -- schedule construction is deterministic and seeded ---------------------------


def test_the_same_seed_produces_the_same_plan() -> None:
    bars = {"AAA": _bars(200)}
    target = MatchTarget(trades_per_ticker={"AAA": 10}, holding_bars=[5, 10, 15])

    plan_a = build_plan(target, bars, random.Random(42))
    plan_b = build_plan(target, bars, random.Random(42))

    assert plan_a == plan_b


def test_different_seeds_produce_different_plans() -> None:
    bars = {"AAA": _bars(200)}
    target = MatchTarget(trades_per_ticker={"AAA": 10}, holding_bars=[5, 10, 15])

    plan_a = build_plan(target, bars, random.Random(1))
    plan_b = build_plan(target, bars, random.Random(2))

    assert plan_a != plan_b


# -- no future sampling, valid trading dates only --------------------------------


def test_every_planned_date_is_an_actual_trading_date() -> None:
    """The schedule must be buildable from the calendar alone -- no entry
    or exit may fall on a date the ticker did not trade."""
    bars = {"AAA": _bars(100)}
    valid_dates = {b.ts.date() for b in bars["AAA"]}
    target = MatchTarget(trades_per_ticker={"AAA": 20}, holding_bars=[3, 5, 8, 12])

    plan = build_plan(target, bars, random.Random(7))

    for trade in plan:
        assert trade.entry_date in valid_dates
        assert trade.exit_date in valid_dates


def test_no_trade_extends_past_the_available_history() -> None:
    bars = {"AAA": _bars(60)}
    last_date = max(b.ts.date() for b in bars["AAA"])
    target = MatchTarget(trades_per_ticker={"AAA": 15}, holding_bars=[10, 20, 30])

    plan = build_plan(target, bars, random.Random(3))

    assert all(t.exit_date <= last_date for t in plan)


def test_warmup_bars_are_never_used_as_an_entry_point() -> None:
    """Matches the fact that a 50-bar moving average cannot signal before
    50 bars exist -- the random arm must not get extra time in the market
    the MA arm could not have had."""
    bars = {"AAA": _bars(150)}
    calendar = sorted({b.ts.date() for b in bars["AAA"]})
    warmup_cutoff = calendar[49]
    target = MatchTarget(trades_per_ticker={"AAA": 30}, holding_bars=[2, 4, 6])

    plan = build_plan(target, bars, random.Random(11), warmup_bars=50)

    assert all(t.entry_date > warmup_cutoff for t in plan)


# -- no overlapping positions in the same name ------------------------------------


def test_positions_in_the_same_ticker_never_overlap() -> None:
    """The MA strategy is long-or-flat. A control that could stack
    positions in one name would not be comparable to it."""
    bars = {"AAA": _bars(300)}
    target = MatchTarget(trades_per_ticker={"AAA": 25}, holding_bars=[5, 10, 15, 20])

    plan = build_plan(target, bars, random.Random(99))

    ordered = sorted(plan, key=lambda t: t.entry_date)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        assert later.entry_date > earlier.exit_date, "overlapping planned trades"


# -- matching and shortfall reporting ---------------------------------------------


def test_target_from_reads_trade_count_and_holding_period_off_the_ma_arm() -> None:
    records = [
        _FakeTrade("AAA", dt.date(2020, 1, 2), dt.date(2020, 1, 6)),
        _FakeTrade("AAA", dt.date(2020, 1, 10), dt.date(2020, 1, 12)),
        _FakeTrade("BBB", dt.date(2020, 1, 5), dt.date(2020, 1, 8)),
    ]
    bars = {"AAA": _bars(30, "AAA"), "BBB": _bars(30, "BBB")}

    target = target_from(records, bars)

    assert target.trades_per_ticker == {"AAA": 2, "BBB": 1}
    assert target.total_trades == 3
    assert len(target.holding_bars) == 3


def test_a_shortfall_is_reported_not_hidden() -> None:
    """A control that quietly placed fewer trades than it claimed would
    understate its activity and flatter the strategy under test."""
    bars = {"AAA": _bars(15)}  # far too little room for 50 trades
    target = MatchTarget(trades_per_ticker={"AAA": 50}, holding_bars=[10])

    plan = build_plan(target, bars, random.Random(5))
    shortfall = plan_shortfall(target, plan)

    assert shortfall.get("AAA", 0) > 0


def test_a_generous_calendar_has_no_shortfall() -> None:
    bars = {"AAA": _bars(500)}
    target = MatchTarget(trades_per_ticker={"AAA": 10}, holding_bars=[5, 10])

    plan = build_plan(target, bars, random.Random(5))

    assert plan_shortfall(target, plan) == {}


def test_an_empty_target_produces_an_empty_plan() -> None:
    bars = {"AAA": _bars(100)}
    assert build_plan(MatchTarget(), bars, random.Random(1)) == []


# -- the strategy executes its schedule and nothing else --------------------------


def test_the_strategy_enters_only_on_its_planned_date() -> None:
    plan = [PlannedTrade("AAA", START.date() + dt.timedelta(days=5),
                         START.date() + dt.timedelta(days=10), 5)]
    strategy = RandomEntryStrategy(plan)
    strategy.on_start()

    from backtesting.market_view import MarketView
    bars = {"AAA": _bars(30, "AAA")}

    before = MarketView.at(bars, START + dt.timedelta(days=4))
    on_day = MarketView.at(bars, START + dt.timedelta(days=5))

    assert strategy.on_bar(before) == []
    signals = strategy.on_bar(on_day)
    assert len(signals) == 1
    assert signals[0].ticker == "AAA"


def test_the_strategy_exits_exactly_on_its_planned_date() -> None:
    from backtesting.market_view import MarketView

    plan = [PlannedTrade("AAA", START.date() + dt.timedelta(days=2),
                         START.date() + dt.timedelta(days=8), 6)]
    strategy = RandomEntryStrategy(plan)
    strategy.on_start()
    bars = {"AAA": _bars(30, "AAA")}

    strategy.on_bar(MarketView.at(bars, START + dt.timedelta(days=2)))
    for day in range(3, 8):
        assert strategy.on_bar(MarketView.at(bars, START + dt.timedelta(days=day))) == []
    exit_signals = strategy.on_bar(MarketView.at(bars, START + dt.timedelta(days=8)))

    assert len(exit_signals) == 1


def test_on_start_resets_open_position_state() -> None:
    """One strategy instance must be reusable across runs -- required for
    the engine's reuse contract, and violated it would leak an open
    position from one Monte Carlo trial into the next."""
    plan = [PlannedTrade("AAA", START.date(), START.date() + dt.timedelta(days=3), 3)]
    strategy = RandomEntryStrategy(plan)
    strategy.on_start()

    from backtesting.market_view import MarketView
    bars = {"AAA": _bars(10, "AAA")}
    strategy.on_bar(MarketView.at(bars, START))  # opens a position

    strategy.on_start()  # reset, as the engine does at the top of every run

    # After reset, the strategy must not remember the still-open position
    # and try to exit something it never (this run) entered.
    result = strategy.on_bar(MarketView.at(bars, START + dt.timedelta(days=3)))
    assert result == []
