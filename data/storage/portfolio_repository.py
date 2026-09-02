"""Paper portfolio persistence and accounting.

The deterministic math lives in `quant.performance.portfolio`; this module
only loads state, applies that math, and writes the result plus an
immutable ledger entry. Position state is therefore always reproducible by
replaying `paper_transactions`.

**No broker connectivity.** `record_buy`/`record_sell` mutate rows in this
database and nothing else (Rule 8).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.asset import Asset
from models.paper_portfolio import PaperPortfolio, PaperPosition, PaperTransaction
from quant.performance.portfolio import (
    InsufficientCashError,
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


@dataclass(frozen=True)
class PositionValuation:
    ticker: str
    quantity: float
    average_cost: float
    current_price: float | None
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    allocation: float


@dataclass(frozen=True)
class PortfolioValuation:
    portfolio_name: str
    base_currency: str
    cash_balance: float
    positions_value: float
    total_equity: float
    exposure: float
    total_return: float
    realized_pnl: float
    unrealized_pnl: float
    positions: list[PositionValuation]
    priced_positions: int
    unpriced_positions: int


def create_portfolio(
    session: Session,
    name: str,
    initial_cash: float,
    base_currency: str = "INR",
    description: str | None = None,
) -> PaperPortfolio:
    if get_portfolio_by_name(session, name) is not None:
        raise PortfolioError(f"Paper portfolio {name!r} already exists")
    portfolio = PaperPortfolio(
        name=name,
        initial_cash=initial_cash,
        cash_balance=initial_cash,
        base_currency=base_currency,
        description=description,
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def get_portfolio_by_name(session: Session, name: str) -> PaperPortfolio | None:
    return session.scalars(select(PaperPortfolio).where(PaperPortfolio.name == name)).first()


def list_portfolios(session: Session) -> list[PaperPortfolio]:
    return list(session.scalars(select(PaperPortfolio).order_by(PaperPortfolio.name)).all())


def get_position(
    session: Session, portfolio: PaperPortfolio, asset: Asset
) -> PaperPosition | None:
    return session.scalars(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.asset_id == asset.id,
        )
    ).first()


def list_positions(
    session: Session, portfolio: PaperPortfolio, open_only: bool = True
) -> list[PaperPosition]:
    query = select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id)
    if open_only:
        query = query.where(PaperPosition.quantity > 0)
    return list(session.scalars(query).all())


def list_transactions(
    session: Session, portfolio: PaperPortfolio, limit: int | None = None
) -> list[PaperTransaction]:
    query = (
        select(PaperTransaction)
        .where(PaperTransaction.portfolio_id == portfolio.id)
        .order_by(PaperTransaction.executed_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query).all())


def _state_of(position: PaperPosition | None) -> PositionState:
    if position is None:
        return PositionState()
    return PositionState(
        quantity=float(position.quantity),
        average_cost=float(position.average_cost),
        realized_pnl=float(position.realized_pnl),
    )


def record_buy(
    session: Session,
    portfolio: PaperPortfolio,
    asset: Asset,
    quantity: float,
    price: float,
    fees: float = 0.0,
    executed_at: dt.datetime | None = None,
    note: str | None = None,
) -> PaperTransaction:
    """Simulated buy. Enforces the cash constraint -- a paper portfolio that
    can spend money it doesn't have teaches the wrong lesson.
    """
    executed_at = executed_at or dt.datetime.now(dt.UTC)
    position = get_position(session, portfolio, asset)
    effect = apply_buy(_state_of(position), quantity, price, fees)

    cash_after = float(portfolio.cash_balance) + effect.cash_delta
    if cash_after < 0:
        raise InsufficientCashError(
            f"Buy needs {abs(effect.cash_delta):.2f} but only "
            f"{float(portfolio.cash_balance):.2f} is available"
        )

    if position is None:
        position = PaperPosition(portfolio_id=portfolio.id, asset_id=asset.id)
        session.add(position)
    if not position.opened_at:
        position.opened_at = executed_at
    position.closed_at = None

    position.quantity = effect.state.quantity
    position.average_cost = effect.state.average_cost
    position.realized_pnl = effect.state.realized_pnl
    portfolio.cash_balance = round(cash_after, 6)

    return _record_transaction(
        session, portfolio, asset, "buy", quantity, price, fees, effect.cash_delta,
        effect.realized_pnl, executed_at, note,
    )


def record_sell(
    session: Session,
    portfolio: PaperPortfolio,
    asset: Asset,
    quantity: float,
    price: float,
    fees: float = 0.0,
    executed_at: dt.datetime | None = None,
    note: str | None = None,
) -> PaperTransaction:
    """Simulated sell. Raises rather than opening a short if oversold."""
    executed_at = executed_at or dt.datetime.now(dt.UTC)
    position = get_position(session, portfolio, asset)
    effect = apply_sell(_state_of(position), quantity, price, fees)

    assert position is not None  # apply_sell rejects selling from an empty state
    position.quantity = effect.state.quantity
    position.average_cost = effect.state.average_cost
    position.realized_pnl = effect.state.realized_pnl
    if effect.state.quantity == 0:
        position.closed_at = executed_at
    portfolio.cash_balance = round(float(portfolio.cash_balance) + effect.cash_delta, 6)

    return _record_transaction(
        session, portfolio, asset, "sell", quantity, price, fees, effect.cash_delta,
        effect.realized_pnl, executed_at, note,
    )


def _record_transaction(
    session: Session,
    portfolio: PaperPortfolio,
    asset: Asset,
    side: str,
    quantity: float,
    price: float,
    fees: float,
    cash_delta: float,
    realized_pnl: float,
    executed_at: dt.datetime,
    note: str | None,
) -> PaperTransaction:
    transaction = PaperTransaction(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        side=side,
        quantity=quantity,
        price=price,
        fees=fees,
        cash_delta=cash_delta,
        realized_pnl=realized_pnl,
        executed_at=executed_at,
        note=note,
    )
    session.add(transaction)
    session.flush()
    return transaction


def value_portfolio(
    session: Session, portfolio: PaperPortfolio, prices: dict[str, float]
) -> PortfolioValuation:
    """Value a portfolio against a {ticker: price} map.

    Positions with no supplied price are reported as **unpriced** and
    excluded from market value rather than being valued at cost -- a stale
    cost basis dressed up as a current value would be fabricated data.
    """
    positions = list_positions(session, portfolio, open_only=True)
    cash = float(portfolio.cash_balance)

    valued: list[PositionValuation] = []
    positions_value = 0.0
    unrealized_total = 0.0
    unpriced = 0

    for position in positions:
        state = _state_of(position)
        ticker = position.asset.ticker
        price = prices.get(ticker)
        if price is None:
            unpriced += 1
            valued.append(
                PositionValuation(
                    ticker=ticker,
                    quantity=state.quantity,
                    average_cost=state.average_cost,
                    current_price=None,
                    market_value=0.0,
                    unrealized_pnl=0.0,
                    realized_pnl=state.realized_pnl,
                    allocation=0.0,
                )
            )
            continue

        value = market_value(state, price)
        positions_value += value
        unrealized_total += unrealized_pnl(state, price)
        valued.append(
            PositionValuation(
                ticker=ticker,
                quantity=state.quantity,
                average_cost=state.average_cost,
                current_price=price,
                market_value=value,
                unrealized_pnl=unrealized_pnl(state, price),
                realized_pnl=state.realized_pnl,
                allocation=0.0,  # filled in below, once equity is known
            )
        )

    equity = total_equity(cash, positions_value)
    valued = [
        PositionValuation(
            **{**v.__dict__, "allocation": allocation(v.market_value, equity)}
        )
        for v in valued
    ]

    realized_total = sum(
        float(p.realized_pnl) for p in list_positions(session, portfolio, open_only=False)
    )

    return PortfolioValuation(
        portfolio_name=portfolio.name,
        base_currency=portfolio.base_currency,
        cash_balance=round(cash, 6),
        positions_value=round(positions_value, 6),
        total_equity=equity,
        exposure=exposure(positions_value, equity),
        total_return=total_return(equity, float(portfolio.initial_cash)),
        realized_pnl=round(realized_total, 6),
        unrealized_pnl=round(unrealized_total, 6),
        positions=valued,
        priced_positions=len(valued) - unpriced,
        unpriced_positions=unpriced,
    )
