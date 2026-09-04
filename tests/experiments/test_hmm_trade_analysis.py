"""HMM state attachment and transition analysis for trades."""

from __future__ import annotations

import datetime as dt

from experiments.hmm_trade_analysis import (
    NO_LABEL,
    analyse_transitions,
    attach,
    by_state,
)
from experiments.trade_analysis import TradeRecord

D = dt.date


def _trade(entry: dt.date, exit_: dt.date, pnl: float = 10.0, ret: float = 0.05) -> TradeRecord:
    return TradeRecord(
        ticker="AAA", entry_date=entry, exit_date=exit_, entry_price=100,
        exit_price=100 + pnl, quantity=1, pnl=pnl, return_pct=ret,
        holding_days=(exit_ - entry).days, mae=-0.02, mfe=0.06,
    )


def _labels(start: D, states: list[int]) -> dict[D, int]:
    return {start + dt.timedelta(days=i): s for i, s in enumerate(states)}


def test_a_trade_wholly_inside_one_state_does_not_transition() -> None:
    labels = _labels(D(2020, 1, 1), [0] * 10)
    trade = _trade(D(2020, 1, 2), D(2020, 1, 5))

    enriched = attach([trade], labels)[0]

    assert enriched.entry_state == 0
    assert enriched.exit_state == 0
    assert not enriched.transitioned


def test_a_trade_spanning_a_state_change_is_marked_transitioned() -> None:
    labels = _labels(D(2020, 1, 1), [0, 0, 0, 1, 1, 1])
    trade = _trade(D(2020, 1, 2), D(2020, 1, 5))  # spans day index 1..4

    enriched = attach([trade], labels)[0]

    assert enriched.entry_state == 0
    assert enriched.exit_state == 1
    assert enriched.transitioned


def test_dates_with_no_label_fall_back_to_the_earlier_one() -> None:
    labels = {D(2020, 1, 1): 0, D(2020, 1, 3): 1}  # day 2 missing
    trade = _trade(D(2020, 1, 2), D(2020, 1, 2))

    enriched = attach([trade], labels)[0]

    assert enriched.entry_state == 0  # falls back to Jan 1, not forward to Jan 3


def test_a_date_entirely_before_any_label_gets_no_label() -> None:
    labels = _labels(D(2020, 6, 1), [0] * 5)
    trade = _trade(D(2020, 1, 1), D(2020, 1, 5))

    enriched = attach([trade], labels)[0]

    assert enriched.entry_state == NO_LABEL
    assert enriched.exit_state == NO_LABEL
    assert not enriched.transitioned  # NO_LABEL trades never count as a transition


def test_empty_labels_yields_no_label_for_every_trade() -> None:
    trades = [_trade(D(2020, 1, 1), D(2020, 1, 5))]

    enriched = attach(trades, {})

    assert all(t.entry_state == NO_LABEL for t in enriched)


def test_by_state_groups_and_computes_expectancy() -> None:
    labels = _labels(D(2020, 1, 1), [0] * 5 + [1] * 5)
    trades = [
        _trade(D(2020, 1, 1), D(2020, 1, 1), pnl=10, ret=0.10),
        _trade(D(2020, 1, 1), D(2020, 1, 1), pnl=20, ret=0.20),
        _trade(D(2020, 1, 8), D(2020, 1, 8), pnl=-5, ret=-0.05),
    ]

    stats = by_state(attach(trades, labels))
    by_id = {s.state: s for s in stats}

    assert by_id[0].trades == 2
    assert by_id[0].expectancy == 0.15
    assert by_id[1].trades == 1
    assert by_id[1].total_pnl == -5.0


def test_no_label_trades_are_grouped_not_dropped() -> None:
    """A silently shrinking denominator is worse than an honest bucket."""
    labels = _labels(D(2022, 1, 1), [0] * 3)
    trades = [_trade(D(2020, 1, 1), D(2020, 1, 2))]  # long before any label

    stats = by_state(attach(trades, labels))

    assert stats[0].state == NO_LABEL
    assert stats[0].trades == 1


def test_profit_factor_is_undefined_with_no_losses() -> None:
    labels = _labels(D(2020, 1, 1), [0] * 5)
    trades = [_trade(D(2020, 1, 1), D(2020, 1, 1), pnl=10, ret=0.1) for _ in range(3)]

    stats = by_state(attach(trades, labels))

    assert stats[0].profit_factor is None


# -- transition analysis -------------------------------------------------------------


def test_transition_analysis_separates_crossing_from_non_crossing() -> None:
    labels = _labels(D(2020, 1, 1), [0, 0, 0, 1, 1, 1])
    trades = [
        _trade(D(2020, 1, 1), D(2020, 1, 2), ret=0.10),  # stays in state 0
        _trade(D(2020, 1, 2), D(2020, 1, 5), ret=-0.20),  # crosses 0 -> 1
        _trade(D(2020, 1, 4), D(2020, 1, 6), ret=0.05),  # stays in state 1
    ]
    enriched = attach(trades, labels)

    result = analyse_transitions(enriched, labels)

    assert result.trades_crossing_a_transition == 1
    assert result.mean_return_crossing == -0.20
    assert result.mean_return_not_crossing == round((0.10 + 0.05) / 2, 6)


def test_no_transitions_in_the_series_yields_no_crossing_trades() -> None:
    labels = _labels(D(2020, 1, 1), [0] * 10)
    trades = [_trade(D(2020, 1, 1), D(2020, 1, 5))]
    enriched = attach(trades, labels)

    result = analyse_transitions(enriched, labels)

    assert result.trades_crossing_a_transition == 0
    assert result.mean_return_crossing is None


def test_an_empty_trade_list_does_not_crash() -> None:
    labels = _labels(D(2020, 1, 1), [0, 1, 0])

    result = analyse_transitions([], labels)

    assert result.trades_crossing_a_transition == 0
    assert result.trades_opened_before_any_transition == 0
