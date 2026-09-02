"""Deterministic portfolio accounting.

Pure functions only -- no database, no clock, no I/O. Position state in,
position state out. Rule 2: these numbers gate what a human is allowed to
act on, so they are computed here and unit-tested against hand-worked
examples, never inferred by an LLM.

Conventions (stated explicitly because they change the numbers):
- Fees are **capitalized into cost basis** on a buy and **deducted from
  proceeds** on a sell.
- Average cost is unchanged by a sell (standard average-cost accounting);
  only quantity and realized P&L move.
- Long-only. Selling more than held raises rather than opening a short --
  see `InsufficientPositionError`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Monetary values are rounded to the precision of the Numeric(18, 6) columns
# they are persisted into, so in-memory and stored state can't drift apart.
_MONEY_DP = 6


class PortfolioError(Exception):
    """Base class for portfolio accounting errors."""


class InsufficientPositionError(PortfolioError):
    """Attempted to sell more units than are held (shorting is not supported)."""


class InsufficientCashError(PortfolioError):
    """Attempted to buy more than the available cash balance allows."""


@dataclass(frozen=True)
class PositionState:
    quantity: float = 0.0
    average_cost: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class TransactionEffect:
    """The outcome of applying one transaction."""

    state: PositionState
    cash_delta: float
    realized_pnl: float = 0.0


def _round(value: float) -> float:
    return round(value, _MONEY_DP)


def apply_buy(
    state: PositionState, quantity: float, price: float, fees: float = 0.0
) -> TransactionEffect:
    if quantity <= 0:
        raise PortfolioError("Buy quantity must be positive")
    if price <= 0:
        raise PortfolioError("Buy price must be positive")

    gross_cost = quantity * price + fees
    prior_basis = state.quantity * state.average_cost
    new_quantity = state.quantity + quantity
    new_average_cost = (prior_basis + gross_cost) / new_quantity

    return TransactionEffect(
        state=PositionState(
            quantity=_round(new_quantity),
            average_cost=_round(new_average_cost),
            realized_pnl=state.realized_pnl,
        ),
        cash_delta=_round(-gross_cost),
    )


def apply_sell(
    state: PositionState, quantity: float, price: float, fees: float = 0.0
) -> TransactionEffect:
    if quantity <= 0:
        raise PortfolioError("Sell quantity must be positive")
    if price <= 0:
        raise PortfolioError("Sell price must be positive")
    if quantity > state.quantity:
        raise InsufficientPositionError(
            f"Cannot sell {quantity} units; only {state.quantity} held "
            "(short positions are not supported)"
        )

    proceeds = quantity * price - fees
    realized = quantity * (price - state.average_cost) - fees
    remaining = state.quantity - quantity

    return TransactionEffect(
        state=PositionState(
            quantity=_round(remaining),
            # A fully-closed position keeps no cost basis.
            average_cost=_round(state.average_cost) if remaining > 0 else 0.0,
            realized_pnl=_round(state.realized_pnl + realized),
        ),
        cash_delta=_round(proceeds),
        realized_pnl=_round(realized),
    )


def market_value(state: PositionState, current_price: float) -> float:
    return _round(state.quantity * current_price)


def unrealized_pnl(state: PositionState, current_price: float) -> float:
    if state.quantity == 0:
        return 0.0
    return _round(state.quantity * (current_price - state.average_cost))


def total_equity(cash_balance: float, positions_market_value: float) -> float:
    return _round(cash_balance + positions_market_value)


def exposure(positions_market_value: float, equity: float) -> float:
    """Invested fraction of equity (1.0 = fully invested, 0.0 = all cash)."""
    if equity == 0:
        return 0.0
    return positions_market_value / equity


def allocation(position_value: float, equity: float) -> float:
    """One position's share of total equity."""
    if equity == 0:
        return 0.0
    return position_value / equity


def total_return(equity: float, initial_cash: float) -> float:
    if initial_cash == 0:
        return 0.0
    return equity / initial_cash - 1
