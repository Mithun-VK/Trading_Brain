from __future__ import annotations

import pytest

from quant.performance.portfolio import (
    InsufficientPositionError,
    PortfolioError,
    PositionState,
    allocation,
    apply_buy,
    apply_sell,
    exposure,
    market_value,
    total_equity,
    total_return,
    unrealized_pnl,
)


def test_first_buy_sets_average_cost() -> None:
    effect = apply_buy(PositionState(), quantity=10, price=100.0)

    assert effect.state.quantity == 10
    assert effect.state.average_cost == 100.0
    assert effect.cash_delta == -1000.0


def test_buy_capitalizes_fees_into_cost_basis() -> None:
    effect = apply_buy(PositionState(), quantity=10, price=100.0, fees=20.0)

    # (10 * 100 + 20) / 10 = 102.0
    assert effect.state.average_cost == 102.0
    assert effect.cash_delta == -1020.0


def test_second_buy_weights_average_cost() -> None:
    first = apply_buy(PositionState(), quantity=10, price=100.0).state
    second = apply_buy(first, quantity=10, price=120.0)

    # (1000 + 1200) / 20 = 110
    assert second.state.quantity == 20
    assert second.state.average_cost == 110.0


def test_partial_sell_realizes_profit_and_keeps_average_cost() -> None:
    held = apply_buy(PositionState(), quantity=10, price=100.0).state

    effect = apply_sell(held, quantity=4, price=130.0)

    assert effect.state.quantity == 6
    assert effect.state.average_cost == 100.0  # unchanged by a sell
    assert effect.realized_pnl == pytest.approx(120.0)  # 4 * (130 - 100)
    assert effect.cash_delta == pytest.approx(520.0)


def test_sell_deducts_fees_from_proceeds_and_pnl() -> None:
    held = apply_buy(PositionState(), quantity=10, price=100.0).state

    effect = apply_sell(held, quantity=10, price=110.0, fees=15.0)

    assert effect.cash_delta == pytest.approx(1085.0)  # 1100 - 15
    assert effect.realized_pnl == pytest.approx(85.0)  # 100 profit - 15 fees


def test_full_sell_clears_cost_basis_but_keeps_realized_pnl() -> None:
    held = apply_buy(PositionState(), quantity=10, price=100.0).state

    effect = apply_sell(held, quantity=10, price=120.0)

    assert effect.state.quantity == 0
    assert effect.state.average_cost == 0.0
    assert effect.state.realized_pnl == pytest.approx(200.0)
    assert not effect.state.is_open


def test_realized_pnl_accumulates_across_sells() -> None:
    state = apply_buy(PositionState(), quantity=10, price=100.0).state
    state = apply_sell(state, quantity=5, price=110.0).state
    state = apply_sell(state, quantity=5, price=90.0).state

    assert state.realized_pnl == pytest.approx(0.0)  # +50 then -50


def test_losing_trade_produces_negative_realized_pnl() -> None:
    held = apply_buy(PositionState(), quantity=10, price=100.0).state

    effect = apply_sell(held, quantity=10, price=80.0)

    assert effect.realized_pnl == pytest.approx(-200.0)


def test_overselling_raises_instead_of_shorting() -> None:
    held = apply_buy(PositionState(), quantity=5, price=100.0).state

    with pytest.raises(InsufficientPositionError, match="short positions are not supported"):
        apply_sell(held, quantity=6, price=100.0)


def test_selling_from_an_empty_position_raises() -> None:
    with pytest.raises(InsufficientPositionError):
        apply_sell(PositionState(), quantity=1, price=100.0)


@pytest.mark.parametrize("quantity", [0, -5])
def test_non_positive_quantities_are_rejected(quantity: float) -> None:
    with pytest.raises(PortfolioError):
        apply_buy(PositionState(), quantity=quantity, price=100.0)


def test_non_positive_price_is_rejected() -> None:
    with pytest.raises(PortfolioError):
        apply_buy(PositionState(), quantity=1, price=0.0)


def test_valuation_helpers() -> None:
    state = PositionState(quantity=10, average_cost=100.0)

    assert market_value(state, 120.0) == 1200.0
    assert unrealized_pnl(state, 120.0) == pytest.approx(200.0)
    assert unrealized_pnl(state, 80.0) == pytest.approx(-200.0)


def test_unrealized_pnl_of_a_flat_position_is_zero() -> None:
    assert unrealized_pnl(PositionState(), 120.0) == 0.0


def test_equity_exposure_and_allocation() -> None:
    equity = total_equity(cash_balance=4000.0, positions_market_value=6000.0)

    assert equity == 10000.0
    assert exposure(6000.0, equity) == pytest.approx(0.6)
    assert allocation(2500.0, equity) == pytest.approx(0.25)


def test_ratios_are_safe_when_equity_is_zero() -> None:
    assert exposure(0.0, 0.0) == 0.0
    assert allocation(0.0, 0.0) == 0.0
    assert total_return(0.0, 0.0) == 0.0


def test_total_return() -> None:
    assert total_return(equity=12000.0, initial_cash=10000.0) == pytest.approx(0.2)
