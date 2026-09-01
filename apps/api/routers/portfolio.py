from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.schemas import PortfolioSummaryOut
from models.trade import Trade

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio/summary", response_model=PortfolioSummaryOut)
def get_portfolio_summary(session: Session = Depends(get_session)) -> PortfolioSummaryOut:
    all_trades = session.scalars(select(Trade)).all()
    open_trades = [t for t in all_trades if t.status == "open"]

    return PortfolioSummaryOut(
        open_trade_count=len(open_trades),
        open_exposure_value=sum(
            float(t.entry_price) * float(t.position_size) for t in open_trades
        ),
        trades_by_status=dict(Counter(t.status for t in all_trades)),
    )
