"""Portfolio tracking over time.

Exposure, returns and allocation are computable from current state (Phase
16). **Drawdown is not** -- it needs an equity history, which is what the
snapshot table provides.

Snapshots record `unpriced_positions` rather than hiding it: a valuation
taken while some holdings had no price available is still useful, but it
must say so instead of implying completeness (Rule 4).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage.portfolio_repository import list_positions, value_portfolio
from data.storage.price_repository import get_price_bars
from models.paper_portfolio import PaperPortfolio
from models.paper_portfolio_snapshot import PaperPortfolioSnapshot
from quant.indicators.returns import max_drawdown, simple_returns, volatility
from quant.performance.stats import cagr, sharpe_ratio, total_return


@dataclass(frozen=True)
class PerformanceSummary:
    portfolio_name: str
    snapshots: int
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    volatility: float
    current_equity: float
    current_exposure: float
    # True when every snapshot in the window priced all its positions.
    fully_priced: bool


def latest_prices(session: Session, portfolio: PaperPortfolio) -> dict[str, float]:
    """Most recent stored close for each open position's ticker.

    Tickers with no stored bars are simply absent, which `value_portfolio`
    reports as unpriced rather than valuing at cost.
    """
    prices: dict[str, float] = {}
    for position in list_positions(session, portfolio, open_only=True):
        bars = get_price_bars(session, position.asset_id, limit=1)
        if bars:
            prices[position.asset.ticker] = float(bars[-1].close)
    return prices


def take_snapshot(
    session: Session,
    portfolio: PaperPortfolio,
    as_of: dt.date | None = None,
    prices: dict[str, float] | None = None,
) -> PaperPortfolioSnapshot:
    """Record today's valuation. Idempotent per (portfolio, date): a re-run
    updates the existing row rather than duplicating it.
    """
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    prices = prices if prices is not None else latest_prices(session, portfolio)
    valuation = value_portfolio(session, portfolio, prices)

    snapshot = session.scalars(
        select(PaperPortfolioSnapshot).where(
            PaperPortfolioSnapshot.portfolio_id == portfolio.id,
            PaperPortfolioSnapshot.as_of == as_of,
        )
    ).first()
    if snapshot is None:
        snapshot = PaperPortfolioSnapshot(portfolio_id=portfolio.id, as_of=as_of)
        session.add(snapshot)

    snapshot.cash = valuation.cash_balance
    snapshot.positions_value = valuation.positions_value
    snapshot.equity = valuation.total_equity
    snapshot.exposure = valuation.exposure
    snapshot.realized_pnl = valuation.realized_pnl
    snapshot.unrealized_pnl = valuation.unrealized_pnl
    snapshot.unpriced_positions = valuation.unpriced_positions
    session.flush()
    return snapshot


def get_snapshots(
    session: Session, portfolio: PaperPortfolio, limit: int | None = None
) -> list[PaperPortfolioSnapshot]:
    rows = list(
        session.scalars(
            select(PaperPortfolioSnapshot)
            .where(PaperPortfolioSnapshot.portfolio_id == portfolio.id)
            .order_by(PaperPortfolioSnapshot.as_of.asc())
        ).all()
    )
    return rows[-limit:] if limit is not None else rows


def performance(
    session: Session, portfolio: PaperPortfolio, periods_per_year: int = 252
) -> PerformanceSummary:
    """Performance over the recorded snapshot history.

    With fewer than two snapshots there is no series to measure, so the
    ratios come back as 0.0 rather than as invented figures.
    """
    snapshots = get_snapshots(session, portfolio)
    equity_series = [float(s.equity) for s in snapshots]
    returns = simple_returns(equity_series) if len(equity_series) >= 2 else []

    current = snapshots[-1] if snapshots else None
    return PerformanceSummary(
        portfolio_name=portfolio.name,
        snapshots=len(snapshots),
        total_return=round(total_return(equity_series), 6) if equity_series else 0.0,
        cagr=round(cagr(equity_series, periods_per_year), 6) if equity_series else 0.0,
        sharpe=round(sharpe_ratio(returns, 0.0, periods_per_year), 6),
        max_drawdown=round(max_drawdown(equity_series), 6),
        volatility=round(volatility(returns, periods_per_year=periods_per_year), 6),
        current_equity=float(current.equity) if current else float(portfolio.initial_cash),
        current_exposure=float(current.exposure) if current else 0.0,
        fully_priced=all(s.unpriced_positions == 0 for s in snapshots),
    )
