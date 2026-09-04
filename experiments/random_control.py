"""Experiment 1 — matched random-entry control.

The decisive falsification test. If MA 20/50 cannot beat randomly timed
entries that are matched on universe, trade count, holding period, sizing,
costs and constraints, then the signal contributes nothing and the V2/V4
results are a property of the universe and the era, not of the strategy.

**What is matched, and why it matters.** A naive random strategy with
arbitrary exposure would lose to almost anything, and beating it would prove
nothing. So the control preserves everything except the timing decision:

    same universe, same bars, same windows, same capital
    same commission and slippage, same sizer, same limits
    same engine  -- literally the same BacktestEngine, so mechanics
                    cannot differ by accident
    same trade count and holding-period distribution as the MA arm

Only *when* to enter is replaced.

**On sampling entry dates from the calendar.** The random arm draws entry
dates from the set of dates on which the ticker actually traded. That set is
knowledge about the future in a strict sense, but it is exactly the same
knowledge the MA arm has -- it too can only act on days that exist. What the
random arm must never see is future *prices*, and it does not: the schedule
is built from the calendar alone, before any bar is examined.
"""

from __future__ import annotations

import datetime as dt
import random
import statistics
from dataclasses import dataclass, field

from backtesting.market_view import MarketView
from backtesting.schemas import SignalAction, StrategySignal
from backtesting.strategy import Strategy
from data.ingestion.schemas import PriceBar


@dataclass(frozen=True)
class PlannedTrade:
    ticker: str
    entry_date: dt.date
    exit_date: dt.date
    holding_bars: int


class RandomEntryStrategy(Strategy):
    """Enters on a pre-drawn schedule and exits after a drawn duration.

    The schedule is fixed before the run begins, so the strategy examines no
    prices at all -- it cannot look ahead because it never looks.
    """

    name = "random_entry"

    def __init__(self, plan: list[PlannedTrade]) -> None:
        self._by_ticker: dict[str, dict[dt.date, PlannedTrade]] = {}
        for trade in plan:
            self._by_ticker.setdefault(trade.ticker, {})[trade.entry_date] = trade
        self._open: dict[str, dt.date] = {}

    def on_start(self) -> None:
        self._open = {}

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        for ticker in view.tickers:
            if not view.is_current(ticker):
                continue
            bar = view.current_bar(ticker)
            if bar is None:
                continue
            today = bar.ts.date()

            exit_on = self._open.get(ticker)
            if exit_on is not None:
                if today >= exit_on:
                    del self._open[ticker]
                    signals.append(
                        StrategySignal(
                            ticker=ticker, action=SignalAction.SELL,
                            reason="planned exit",
                        )
                    )
                continue

            planned = self._by_ticker.get(ticker, {}).get(today)
            if planned is not None:
                self._open[ticker] = planned.exit_date
                signals.append(
                    StrategySignal(
                        ticker=ticker, action=SignalAction.BUY,
                        reason="planned entry",
                    )
                )
        return signals


# -- building a matched schedule ------------------------------------------------


@dataclass
class MatchTarget:
    """What the random arm is being matched against.

    Derived from the MA arm's realised behaviour, never chosen by hand --
    a control matched to a number someone picked is not a control.
    """

    trades_per_ticker: dict[str, int] = field(default_factory=dict)
    holding_bars: list[int] = field(default_factory=list)
    total_trades: int = 0

    @property
    def median_holding(self) -> float | None:
        return statistics.median(self.holding_bars) if self.holding_bars else None


def target_from(records, bars_by_ticker: dict[str, list[PriceBar]]) -> MatchTarget:
    """Extract the matching targets from the MA arm's own trades."""
    target = MatchTarget()
    calendars = {t: _calendar(bars) for t, bars in bars_by_ticker.items()}

    for record in records:
        target.trades_per_ticker[record.ticker] = (
            target.trades_per_ticker.get(record.ticker, 0) + 1
        )
        target.total_trades += 1
        calendar = calendars.get(record.ticker, [])
        held = _bars_between(calendar, record.entry_date, record.exit_date)
        if held > 0:
            target.holding_bars.append(held)

    return target


def _calendar(bars: list[PriceBar]) -> list[dt.date]:
    return sorted({b.ts.date() for b in bars})


def _bars_between(calendar: list[dt.date], start: dt.date, end: dt.date) -> int:
    return sum(1 for d in calendar if start < d <= end)


def build_plan(
    target: MatchTarget,
    bars_by_ticker: dict[str, list[PriceBar]],
    rng: random.Random,
    *,
    warmup_bars: int = 50,
) -> list[PlannedTrade]:
    """Draw a random schedule matched to `target`.

    Entries are drawn without replacement per ticker so two positions in the
    same name cannot overlap -- the MA strategy is long-or-flat, and a
    control that could stack positions would not be comparable.

    `warmup_bars` skips the start of the window, matching the fact that a
    50-bar moving average cannot signal before 50 bars exist. Without it the
    random arm would get extra time in the market that the MA arm could not
    have had.
    """
    plan: list[PlannedTrade] = []
    if not target.holding_bars:
        return plan

    for ticker, count in sorted(target.trades_per_ticker.items()):
        calendar = _calendar(bars_by_ticker.get(ticker, []))
        if len(calendar) <= warmup_bars + 1:
            continue
        eligible = calendar[warmup_bars:]

        occupied: set[int] = set()
        attempts = 0
        placed = 0
        # Bounded: a dense schedule can genuinely run out of room, and
        # spinning forever to force an exact match would be worse than
        # reporting a shortfall.
        max_attempts = count * 50

        while placed < count and attempts < max_attempts:
            attempts += 1
            index = rng.randrange(len(eligible))
            held = rng.choice(target.holding_bars)
            end_index = index + held
            if end_index >= len(eligible):
                continue
            span = range(index, end_index + 1)
            if any(i in occupied for i in span):
                continue
            occupied.update(span)
            plan.append(
                PlannedTrade(
                    ticker=ticker,
                    entry_date=eligible[index],
                    exit_date=eligible[end_index],
                    holding_bars=held,
                )
            )
            placed += 1

    return plan


def plan_shortfall(target: MatchTarget, plan: list[PlannedTrade]) -> dict[str, int]:
    """Where the schedule could not place every requested trade.

    Reported rather than hidden: a control that quietly placed 80% of the
    trades it claimed would understate the random arm's activity and flatter
    the strategy.
    """
    placed: dict[str, int] = {}
    for trade in plan:
        placed[trade.ticker] = placed.get(trade.ticker, 0) + 1
    return {
        ticker: wanted - placed.get(ticker, 0)
        for ticker, wanted in target.trades_per_ticker.items()
        if wanted - placed.get(ticker, 0) > 0
    }
