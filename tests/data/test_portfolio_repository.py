from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from data.storage.portfolio_repository import (
    create_portfolio,
    get_position,
    list_positions,
    list_transactions,
    record_buy,
    record_sell,
    value_portfolio,
)
from models.base import Base
from quant.performance.portfolio import (
    InsufficientCashError,
    InsufficientPositionError,
    PortfolioError,
)

EXECUTED_AT = dt.datetime(2026, 1, 10, tzinfo=dt.UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def portfolio(session: Session) -> models.PaperPortfolio:
    return create_portfolio(session, "Core", initial_cash=100_000.0)


def _asset(session: Session, ticker: str) -> models.Asset:
    asset = models.Asset(ticker=ticker, exchange="NSE", asset_type="equity", name=ticker)
    session.add(asset)
    session.flush()
    return asset


def test_create_portfolio_starts_fully_in_cash(session: Session) -> None:
    portfolio = create_portfolio(session, "Core", initial_cash=50_000.0)
    session.commit()

    assert float(portfolio.cash_balance) == 50_000.0
    assert float(portfolio.initial_cash) == 50_000.0


def test_duplicate_portfolio_name_is_rejected(session: Session) -> None:
    create_portfolio(session, "Core", initial_cash=1000.0)
    session.commit()

    with pytest.raises(PortfolioError, match="already exists"):
        create_portfolio(session, "Core", initial_cash=1000.0)


def test_buy_creates_position_and_debits_cash(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")

    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == 10
    assert float(position.average_cost) == 1000.0
    assert float(portfolio.cash_balance) == 90_000.0
    assert position.opened_at is not None


def test_buy_is_rejected_when_cash_is_insufficient(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    """A paper portfolio that can spend money it doesn't have teaches nothing."""
    asset = _asset(session, "RELIANCE")

    with pytest.raises(InsufficientCashError):
        record_buy(session, portfolio, asset, quantity=1000, price=1000.0)


def test_second_buy_averages_cost(session: Session, portfolio: models.PaperPortfolio) -> None:
    asset = _asset(session, "RELIANCE")

    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_buy(session, portfolio, asset, quantity=10, price=1200.0, executed_at=EXECUTED_AT)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == 20
    assert float(position.average_cost) == 1100.0
    assert float(portfolio.cash_balance) == 78_000.0


def test_sell_credits_cash_and_records_realized_pnl(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)

    record_sell(session, portfolio, asset, quantity=4, price=1300.0, executed_at=EXECUTED_AT)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == 6
    assert float(position.realized_pnl) == pytest.approx(1200.0)
    assert float(portfolio.cash_balance) == pytest.approx(95_200.0)


def test_full_sell_closes_the_position_but_keeps_the_row(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)

    record_sell(session, portfolio, asset, quantity=10, price=1100.0, executed_at=EXECUTED_AT)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == 0
    assert position.closed_at is not None
    assert float(position.realized_pnl) == pytest.approx(1000.0)
    assert list_positions(session, portfolio, open_only=True) == []


def test_overselling_is_rejected(session: Session, portfolio: models.PaperPortfolio) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=5, price=1000.0, executed_at=EXECUTED_AT)

    with pytest.raises(InsufficientPositionError):
        record_sell(session, portfolio, asset, quantity=6, price=1000.0)


def test_transactions_form_an_immutable_ledger(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_sell(session, portfolio, asset, quantity=5, price=1100.0, executed_at=EXECUTED_AT)
    session.commit()

    ledger = list_transactions(session, portfolio)
    assert len(ledger) == 2
    assert {t.side for t in ledger} == {"buy", "sell"}
    # Cash movements in the ledger must reconcile with the balance.
    assert float(portfolio.cash_balance) == pytest.approx(
        100_000.0 + sum(float(t.cash_delta) for t in ledger)
    )


def test_re_entry_after_a_close_keeps_cumulative_realized_pnl(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_sell(session, portfolio, asset, quantity=10, price=1100.0, executed_at=EXECUTED_AT)

    record_buy(session, portfolio, asset, quantity=5, price=900.0, executed_at=EXECUTED_AT)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == 5
    assert float(position.average_cost) == 900.0
    assert float(position.realized_pnl) == pytest.approx(1000.0)  # survived the round trip
    assert position.closed_at is None  # reopened


def test_value_portfolio_computes_equity_exposure_and_allocation(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    reliance = _asset(session, "RELIANCE")
    tcs = _asset(session, "TCS")
    record_buy(session, portfolio, reliance, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_buy(session, portfolio, tcs, quantity=10, price=2000.0, executed_at=EXECUTED_AT)
    session.commit()

    valuation = value_portfolio(session, portfolio, prices={"RELIANCE": 1200.0, "TCS": 1800.0})

    # cash 70,000 + positions (12,000 + 18,000) = 100,000
    assert valuation.cash_balance == pytest.approx(70_000.0)
    assert valuation.positions_value == pytest.approx(30_000.0)
    assert valuation.total_equity == pytest.approx(100_000.0)
    assert valuation.exposure == pytest.approx(0.3)
    assert valuation.unrealized_pnl == pytest.approx(0.0)  # +2000 and -2000
    assert valuation.total_return == pytest.approx(0.0)

    by_ticker = {p.ticker: p for p in valuation.positions}
    assert by_ticker["RELIANCE"].allocation == pytest.approx(0.12)
    assert by_ticker["TCS"].unrealized_pnl == pytest.approx(-2000.0)


def test_unpriced_positions_are_reported_not_valued_at_cost(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    """Valuing a position at its cost basis would present stale data as current."""
    reliance = _asset(session, "RELIANCE")
    tcs = _asset(session, "TCS")
    record_buy(session, portfolio, reliance, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_buy(session, portfolio, tcs, quantity=10, price=2000.0, executed_at=EXECUTED_AT)
    session.commit()

    valuation = value_portfolio(session, portfolio, prices={"RELIANCE": 1200.0})

    assert valuation.priced_positions == 1
    assert valuation.unpriced_positions == 1
    assert valuation.positions_value == pytest.approx(12_000.0)
    unpriced = next(p for p in valuation.positions if p.ticker == "TCS")
    assert unpriced.current_price is None
    assert unpriced.market_value == 0.0


def test_value_of_an_all_cash_portfolio(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    session.commit()

    valuation = value_portfolio(session, portfolio, prices={})

    assert valuation.total_equity == pytest.approx(100_000.0)
    assert valuation.exposure == 0.0
    assert valuation.positions == []


def test_realized_gain_shows_up_in_total_return(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    asset = _asset(session, "RELIANCE")
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=EXECUTED_AT)
    record_sell(session, portfolio, asset, quantity=10, price=1500.0, executed_at=EXECUTED_AT)
    session.commit()

    valuation = value_portfolio(session, portfolio, prices={})

    assert valuation.total_equity == pytest.approx(105_000.0)
    assert valuation.realized_pnl == pytest.approx(5_000.0)
    assert valuation.total_return == pytest.approx(0.05)
