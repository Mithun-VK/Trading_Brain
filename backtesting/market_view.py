"""Anti-lookahead market view.

The most dangerous bug in a backtester is a strategy seeing data it could
not have had. This module makes that **structurally impossible** rather
than merely discouraged: a strategy is never handed the underlying price
series, only a `MarketView` that has already been sliced to the current
bar. There is no accessor that reaches beyond it, so future data is not
"forbidden" -- it is absent.

The engine's execution model closes the remaining gap: signals are computed
from data through bar *i*'s close, and the resulting orders fill at bar
*i+1*'s open. Filling at the same bar's close would be lookahead, because
you cannot act on a price at the instant you first observe it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from data.ingestion.schemas import PriceBar


@dataclass(frozen=True)
class MarketView:
    """History up to and including the current timeline step.

    Construct via `MarketView.at()`; the constructor takes pre-sliced data
    so no caller can hand a strategy more than it should see.
    """

    timestamp: dt.datetime
    _history: dict[str, list[PriceBar]]

    @classmethod
    def at(
        cls,
        bars_by_ticker: dict[str, list[PriceBar]],
        timestamp: dt.datetime,
    ) -> MarketView:
        """Slice every series to bars at or before `timestamp`."""
        sliced = {
            ticker: [bar for bar in bars if bar.ts <= timestamp]
            for ticker, bars in bars_by_ticker.items()
        }
        return cls(timestamp=timestamp, _history={t: b for t, b in sliced.items() if b})

    @property
    def tickers(self) -> list[str]:
        return sorted(self._history)

    def has_data(self, ticker: str) -> bool:
        return ticker in self._history

    def bars(self, ticker: str, lookback: int | None = None) -> list[PriceBar]:
        """Bars for `ticker`, oldest first, ending at the current step."""
        history = self._history.get(ticker, [])
        return list(history[-lookback:]) if lookback is not None else list(history)

    def closes(self, ticker: str, lookback: int | None = None) -> list[float]:
        return [bar.close for bar in self.bars(ticker, lookback)]

    def current_bar(self, ticker: str) -> PriceBar | None:
        """The most recent bar at or before now -- None if this ticker has
        no data yet, or didn't trade on this timestamp.
        """
        history = self._history.get(ticker)
        return history[-1] if history else None

    def current_price(self, ticker: str) -> float | None:
        bar = self.current_bar(ticker)
        return bar.close if bar else None

    def is_current(self, ticker: str) -> bool:
        """True when this ticker actually printed a bar on this timestamp
        (as opposed to a stale carried-forward one).
        """
        bar = self.current_bar(ticker)
        return bar is not None and bar.ts == self.timestamp

    def bar_count(self, ticker: str) -> int:
        return len(self._history.get(ticker, []))
