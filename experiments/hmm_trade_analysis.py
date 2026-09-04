"""Experiment 3 — attaching HMM states to trades.

Mirrors `trade_analysis.by_regime` in shape (trades, win rate, expectancy,
profit factor, MAE/MFE, significance flag), but keyed by persistent HMM
state id rather than the V4 heuristic `Regime` enum -- the two taxonomies
are independent, and this module never imports `regimes.py`.

Trades whose entry date falls before the HMM's usable history (the model
needs a training fold before it can label anything) are grouped under
state `-1` rather than dropped, for the same reason V4 groups
`Regime.UNKNOWN` rather than discarding it: a silently shrinking
denominator is worse than an honest "not labelled" bucket.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from experiments.trade_analysis import MIN_TRADES_FOR_SIGNIFICANCE, TradeRecord

NO_LABEL = -1


@dataclass
class HMMTradeRecord:
    ticker: str
    entry_date: dt.date
    exit_date: dt.date
    entry_state: int
    exit_state: int
    transitioned: bool
    states_visited: tuple[int, ...]
    return_pct: float
    pnl: float
    mae: float | None
    mfe: float | None
    holding_days: float

    def to_dict(self) -> dict:
        return {**self.__dict__, "states_visited": list(self.states_visited)}


def attach(
    records: list[TradeRecord], labels_by_date: dict[dt.date, int]
) -> list[HMMTradeRecord]:
    if not labels_by_date:
        return [
            HMMTradeRecord(
                ticker=r.ticker, entry_date=r.entry_date, exit_date=r.exit_date,
                entry_state=NO_LABEL, exit_state=NO_LABEL, transitioned=False,
                states_visited=(), return_pct=r.return_pct, pnl=r.pnl,
                mae=r.mae, mfe=r.mfe, holding_days=r.holding_days,
            )
            for r in records
        ]

    dates = sorted(labels_by_date)

    def lookup(when: dt.date) -> int:
        if when in labels_by_date:
            return labels_by_date[when]
        earlier = [d for d in dates if d < when]
        return labels_by_date[max(earlier)] if earlier else NO_LABEL

    out = []
    for r in records:
        entry_state = lookup(r.entry_date)
        exit_state = lookup(r.exit_date)
        visited = tuple(sorted({
            labels_by_date[d] for d in dates if r.entry_date <= d <= r.exit_date
        }))
        out.append(
            HMMTradeRecord(
                ticker=r.ticker, entry_date=r.entry_date, exit_date=r.exit_date,
                entry_state=entry_state, exit_state=exit_state,
                transitioned=entry_state != exit_state and entry_state != NO_LABEL
                and exit_state != NO_LABEL,
                states_visited=visited, return_pct=r.return_pct, pnl=r.pnl,
                mae=r.mae, mfe=r.mfe, holding_days=r.holding_days,
            )
        )
    return out


@dataclass
class HMMStateStats:
    state: int
    trades: int = 0
    total_pnl: float = 0.0
    win_rate: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    average_mae: float | None = None
    average_mfe: float | None = None
    average_holding_days: float | None = None
    is_significant: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def by_state(records: list[HMMTradeRecord], *, key: str = "entry_state") -> list[HMMStateStats]:
    groups: dict[int, list[HMMTradeRecord]] = {}
    for r in records:
        groups.setdefault(getattr(r, key), []).append(r)

    out = []
    for state, trades in groups.items():
        returns = [t.return_pct for t in trades]
        wins = sum(1 for r in returns if r > 0)
        gross_win = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        maes = [t.mae for t in trades if t.mae is not None]
        mfes = [t.mfe for t in trades if t.mfe is not None]

        out.append(
            HMMStateStats(
                state=state,
                trades=len(trades),
                total_pnl=round(sum(t.pnl for t in trades), 2),
                win_rate=round(wins / len(trades), 4) if trades else None,
                expectancy=round(sum(returns) / len(returns), 6) if returns else None,
                profit_factor=round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
                average_mae=round(sum(maes) / len(maes), 6) if maes else None,
                average_mfe=round(sum(mfes) / len(mfes), 6) if mfes else None,
                average_holding_days=(
                    round(sum(t.holding_days for t in trades) / len(trades), 2) if trades else None
                ),
                is_significant=len(trades) >= MIN_TRADES_FOR_SIGNIFICANCE,
            )
        )
    return sorted(out, key=lambda s: s.total_pnl, reverse=True)


@dataclass
class TransitionAnalysis:
    """Trades in relation to a state change, per the brief's mandatory
    transition analysis section."""

    trades_opened_before_any_transition: int
    trades_opened_after_a_transition: int  # entered the same day the state changed
    trades_crossing_a_transition: int
    mean_return_crossing: float | None
    mean_return_not_crossing: float | None
    mean_mae_crossing: float | None
    mean_mae_not_crossing: float | None
    mean_holding_crossing: float | None
    mean_holding_not_crossing: float | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def analyse_transitions(
    records: list[HMMTradeRecord], labels_by_date: dict[dt.date, int]
) -> TransitionAnalysis:
    """Does the strategy behave differently around a latent-state change?

    A trade "crosses" a transition when it visited more than one state
    during its holding period -- computed already in `attach()` via
    `states_visited`.
    """
    dates = sorted(labels_by_date)
    transition_dates = {
        dates[i]
        for i in range(1, len(dates))
        if labels_by_date[dates[i]] != labels_by_date[dates[i - 1]]
    }

    crossing = [r for r in records if r.transitioned]
    not_crossing = [r for r in records if not r.transitioned]
    opened_after = [r for r in records if r.entry_date in transition_dates]

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None

    return TransitionAnalysis(
        trades_opened_before_any_transition=len(records) - len(opened_after),
        trades_opened_after_a_transition=len(opened_after),
        trades_crossing_a_transition=len(crossing),
        mean_return_crossing=avg([r.return_pct for r in crossing]),
        mean_return_not_crossing=avg([r.return_pct for r in not_crossing]),
        mean_mae_crossing=avg([r.mae for r in crossing if r.mae is not None]),
        mean_mae_not_crossing=avg([r.mae for r in not_crossing if r.mae is not None]),
        mean_holding_crossing=avg([r.holding_days for r in crossing]),
        mean_holding_not_crossing=avg([r.holding_days for r in not_crossing]),
    )
