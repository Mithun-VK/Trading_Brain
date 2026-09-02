"""Portfolio API.

Every figure comes from `paper_trading.service` / `data.storage.portfolio_repository`
/ `quant.performance.portfolio`. This router composes responses; it does not
compute portfolio maths.

`/portfolio/summary` (Phase 12) is kept for backwards compatibility.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.schemas import PortfolioSummaryOut
from apps.api.schemas_v2 import (
    ExposureBucketOut,
    ExposureOut,
    PortfolioOut,
    PortfolioPerformanceOut,
    PositionOut,
)
from models.trade import Trade
from paper_trading.service import (
    PortfolioNotFoundError,
    exposure_for,
    performance_for,
    resolve_portfolio,
    valuation_for,
)

router = APIRouter(tags=["portfolio"])


def _resolve(session: Session, name: str | None):
    try:
        return resolve_portfolio(session, name)
    except PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(
    name: str | None = None, session: Session = Depends(get_session)
) -> PortfolioOut:
    portfolio = _resolve(session, name)
    valuation = valuation_for(session, portfolio)

    return PortfolioOut(
        portfolio_name=valuation.portfolio_name,
        base_currency=valuation.base_currency,
        cash=valuation.cash_balance,
        positions_value=valuation.positions_value,
        total_value=valuation.total_equity,
        unrealized_pnl=valuation.unrealized_pnl,
        realized_pnl=valuation.realized_pnl,
        total_return=valuation.total_return,
        exposure=valuation.exposure,
        position_count=len(valuation.positions),
        unpriced_positions=valuation.unpriced_positions,
    )


@router.get("/portfolio/positions", response_model=list[PositionOut])
def get_positions(
    name: str | None = None, session: Session = Depends(get_session)
) -> list[PositionOut]:
    portfolio = _resolve(session, name)
    valuation = valuation_for(session, portfolio)

    return [
        PositionOut(
            ticker=p.ticker,
            quantity=p.quantity,
            average_cost=p.average_cost,
            current_price=p.current_price,
            market_value=p.market_value,
            unrealized_pnl=p.unrealized_pnl,
            realized_pnl=p.realized_pnl,
            allocation=p.allocation,
            unpriced=p.current_price is None,
        )
        for p in valuation.positions
    ]


@router.get("/portfolio/performance", response_model=PortfolioPerformanceOut)
def get_performance(
    name: str | None = None, session: Session = Depends(get_session)
) -> PortfolioPerformanceOut:
    portfolio = _resolve(session, name)
    summary, daily_return, caveat = performance_for(session, portfolio)

    return PortfolioPerformanceOut(
        portfolio_name=summary.portfolio_name,
        snapshots=summary.snapshots,
        total_return=summary.total_return,
        daily_return=daily_return,
        cagr=summary.cagr,
        sharpe=summary.sharpe,
        volatility=summary.volatility,
        max_drawdown=summary.max_drawdown,
        current_equity=summary.current_equity,
        current_exposure=summary.current_exposure,
        fully_priced=summary.fully_priced,
        caveat=caveat,
    )


@router.get("/portfolio/exposure", response_model=ExposureOut)
def get_exposure(
    name: str | None = None, session: Session = Depends(get_session)
) -> ExposureOut:
    portfolio = _resolve(session, name)
    breakdown = exposure_for(session, portfolio)

    return ExposureOut(
        portfolio_name=breakdown.portfolio_name,
        gross_exposure=breakdown.gross_exposure,
        cash_weight=breakdown.cash_weight,
        by_sector=[
            ExposureBucketOut(label=b.label, value=b.value, weight=b.weight)
            for b in breakdown.by_sector
        ],
        by_asset=[
            ExposureBucketOut(label=b.label, value=b.value, weight=b.weight)
            for b in breakdown.by_asset
        ],
        unpriced_positions=breakdown.unpriced_positions,
    )


@router.get("/portfolio/allocation", response_model=list[ExposureBucketOut])
def get_allocation(
    name: str | None = None, session: Session = Depends(get_session)
) -> list[ExposureBucketOut]:
    """Per-asset weights of total equity. Unpriced positions are omitted
    rather than shown at cost.
    """
    portfolio = _resolve(session, name)
    breakdown = exposure_for(session, portfolio)
    return [
        ExposureBucketOut(label=b.label, value=b.value, weight=b.weight)
        for b in breakdown.by_asset
    ]


@router.get("/portfolio/summary", response_model=PortfolioSummaryOut)
def get_portfolio_summary(session: Session = Depends(get_session)) -> PortfolioSummaryOut:
    """Legacy Phase 12 endpoint: trade-derived, not paper-portfolio based."""
    all_trades = session.scalars(select(Trade)).all()
    open_trades = [t for t in all_trades if t.status == "open"]

    return PortfolioSummaryOut(
        open_trade_count=len(open_trades),
        open_exposure_value=sum(
            float(t.entry_price) * float(t.position_size) for t in open_trades
        ),
        trades_by_status=dict(Counter(t.status for t in all_trades)),
    )
