"""Portfolio/paper-trade application service.

Sits between the API and the repositories so routers stay transport-only.
Every figure here comes from an existing domain function
(`quant.performance.portfolio`, `paper_trading.tracking`) -- this module
composes, it does not calculate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage.portfolio_repository import (
    PortfolioValuation,
    get_portfolio_by_name,
    list_portfolios,
    list_positions,
    value_portfolio,
)
from models.company import Company
from models.paper_portfolio import PaperPortfolio
from models.trade import Trade
from paper_trading.tracking import PerformanceSummary, latest_prices, performance


class PortfolioNotFoundError(Exception):
    """No paper portfolio matched the request."""


@dataclass(frozen=True)
class ExposureBucket:
    label: str
    value: float
    weight: float


@dataclass
class ExposureBreakdown:
    portfolio_name: str
    gross_exposure: float = 0.0
    cash_weight: float = 0.0
    by_sector: list[ExposureBucket] = field(default_factory=list)
    by_asset: list[ExposureBucket] = field(default_factory=list)
    unpriced_positions: int = 0


def resolve_portfolio(session: Session, name: str | None = None) -> PaperPortfolio:
    """Resolve a portfolio by name, or the only one if unambiguous."""
    if name:
        portfolio = get_portfolio_by_name(session, name)
        if portfolio is None:
            raise PortfolioNotFoundError(f"No paper portfolio named {name!r}")
        return portfolio

    portfolios = list_portfolios(session)
    if not portfolios:
        raise PortfolioNotFoundError("No paper portfolio exists yet")
    if len(portfolios) > 1:
        names = ", ".join(p.name for p in portfolios)
        raise PortfolioNotFoundError(
            f"Multiple portfolios exist ({names}); specify one by name"
        )
    return portfolios[0]


def valuation_for(session: Session, portfolio: PaperPortfolio) -> PortfolioValuation:
    """Current valuation using the latest stored closes."""
    return value_portfolio(session, portfolio, latest_prices(session, portfolio))


def performance_for(
    session: Session, portfolio: PaperPortfolio
) -> tuple[PerformanceSummary, float | None, str | None]:
    """Performance plus the most recent daily return and any caveat.

    `daily_return` is None with fewer than two snapshots -- one data point
    is not a return, and reporting 0.0 would imply a flat day that was
    never observed.
    """
    from paper_trading.tracking import get_snapshots

    summary = performance(session, portfolio)
    snapshots = get_snapshots(session, portfolio)

    daily_return: float | None = None
    if len(snapshots) >= 2:
        previous, latest = float(snapshots[-2].equity), float(snapshots[-1].equity)
        if previous:
            daily_return = round(latest / previous - 1, 6)

    caveat = None
    if summary.snapshots < 2:
        caveat = (
            "Fewer than two portfolio snapshots recorded; return and risk "
            "figures are not yet meaningful."
        )
    elif not summary.fully_priced:
        caveat = (
            "At least one snapshot was taken while a position had no price "
            "available, so equity history is incomplete."
        )

    return summary, daily_return, caveat


def exposure_for(session: Session, portfolio: PaperPortfolio) -> ExposureBreakdown:
    """Gross exposure split by sector and by asset.

    Weights are of total equity, so cash_weight + gross_exposure == 1.0
    when every position is priced.
    """
    valuation = valuation_for(session, portfolio)
    equity = valuation.total_equity
    breakdown = ExposureBreakdown(
        portfolio_name=portfolio.name,
        gross_exposure=round(valuation.exposure, 6),
        cash_weight=round(valuation.cash_balance / equity, 6) if equity else 0.0,
        unpriced_positions=valuation.unpriced_positions,
    )

    sector_values: dict[str, float] = {}
    for position in list_positions(session, portfolio, open_only=True):
        priced = next(
            (p for p in valuation.positions if p.ticker == position.asset.ticker), None
        )
        if priced is None or priced.current_price is None:
            continue
        company = session.scalars(
            select(Company).where(Company.asset_id == position.asset_id)
        ).first()
        sector = company.sector if company and company.sector else "unknown sector"
        sector_values[sector] = sector_values.get(sector, 0.0) + priced.market_value

    breakdown.by_sector = [
        ExposureBucket(
            label=label,
            value=round(value, 6),
            weight=round(value / equity, 6) if equity else 0.0,
        )
        for label, value in sorted(sector_values.items(), key=lambda kv: -kv[1])
    ]
    breakdown.by_asset = [
        ExposureBucket(
            label=p.ticker,
            value=p.market_value,
            weight=round(p.allocation, 6),
        )
        for p in valuation.positions
        if p.current_price is not None
    ]
    return breakdown


def holding_period_days(trade: Trade) -> int | None:
    if trade.closed_at is None:
        return None
    opened = trade.opened_at
    closed = trade.closed_at
    if opened.tzinfo is None and closed.tzinfo is not None:
        opened = opened.replace(tzinfo=closed.tzinfo)
    if closed.tzinfo is None and opened.tzinfo is not None:
        closed = closed.replace(tzinfo=opened.tzinfo)
    return (closed - opened).days


def trade_pnl(trade: Trade, exit_price: float | None = None) -> float | None:
    """Realized PnL for a closed trade, or None while it is still open."""
    if trade.status != "closed":
        return None
    if exit_price is None:
        return None
    return round(
        (exit_price - float(trade.entry_price)) * float(trade.position_size), 6
    )


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
