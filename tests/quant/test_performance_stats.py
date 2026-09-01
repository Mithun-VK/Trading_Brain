from __future__ import annotations

import math

from quant.performance.stats import (
    average_loser,
    average_winner,
    cagr,
    expectancy,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)


def test_total_return() -> None:
    assert total_return([100, 150]) == 0.5


def test_total_return_insufficient_data() -> None:
    assert total_return([100]) == 0.0


def test_cagr_one_year_doubling() -> None:
    assert cagr([100, 200], periods_per_year=1) == 1.0


def test_sharpe_ratio_zero_variance_is_zero() -> None:
    assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0


def test_sharpe_ratio_positive_for_positive_mean_returns() -> None:
    result = sharpe_ratio([0.01, 0.02, -0.005, 0.015], periods_per_year=252)

    assert result > 0


def test_sortino_ratio_ignores_upside_deviation() -> None:
    # All-positive returns: no downside deviation -> ratio is 0 (guarded, not inf/NaN).
    assert sortino_ratio([0.01, 0.02, 0.03]) == 0.0


def test_sortino_ratio_positive_for_positive_skew() -> None:
    result = sortino_ratio([0.02, -0.01, 0.03, -0.005])

    assert result > 0
    assert not math.isnan(result)


def test_win_rate() -> None:
    assert win_rate([10, -5, 20, -1, 0]) == 0.4


def test_win_rate_empty() -> None:
    assert win_rate([]) == 0.0


def test_profit_factor() -> None:
    assert profit_factor([10, -5, 20, -10]) == 2.0


def test_profit_factor_no_losses() -> None:
    assert profit_factor([10, 20]) == float("inf")


def test_profit_factor_no_trades() -> None:
    assert profit_factor([]) == 0.0


def test_expectancy() -> None:
    assert expectancy([10, -5, 20, -10]) == 3.75


def test_average_winner() -> None:
    assert average_winner([10, -5, 20, -10]) == 15


def test_average_loser() -> None:
    assert average_loser([10, -5, 20, -10]) == -7.5


def test_average_winner_no_winners() -> None:
    assert average_winner([-5, -10]) == 0.0
