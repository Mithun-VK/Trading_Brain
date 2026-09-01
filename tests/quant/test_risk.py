from __future__ import annotations

import pytest

from quant.performance.risk import portfolio_exposure, position_size, r_multiple, risk_amount


def test_risk_amount() -> None:
    assert risk_amount(10_000, 0.01) == 100


def test_position_size() -> None:
    size = position_size(
        account_equity=10_000, risk_per_trade_pct=0.01, entry_price=100, stop_price=95
    )

    assert size == 20


def test_position_size_rejects_equal_entry_and_stop() -> None:
    with pytest.raises(ValueError):
        position_size(10_000, 0.01, 100, 100)


def test_r_multiple_long_win() -> None:
    assert r_multiple(entry_price=100, stop_price=95, exit_price=110, direction="long") == 2.0


def test_r_multiple_long_loss() -> None:
    assert r_multiple(entry_price=100, stop_price=95, exit_price=95, direction="long") == -1.0


def test_r_multiple_short_win() -> None:
    assert r_multiple(entry_price=100, stop_price=105, exit_price=90, direction="short") == 2.0


def test_r_multiple_rejects_bad_direction() -> None:
    with pytest.raises(ValueError):
        r_multiple(100, 95, 110, direction="sideways")


def test_r_multiple_rejects_equal_entry_and_stop() -> None:
    with pytest.raises(ValueError):
        r_multiple(100, 100, 110)


def test_portfolio_exposure() -> None:
    assert portfolio_exposure([5_000, 3_000], 10_000) == 0.8


def test_portfolio_exposure_rejects_zero_equity() -> None:
    with pytest.raises(ValueError):
        portfolio_exposure([1_000], 0)
