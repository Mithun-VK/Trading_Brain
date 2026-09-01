"""Note: `/market/regime` must be registered before `/market/{ticker}` --
otherwise FastAPI would match "regime" as the ticker path parameter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_market_data, get_session
from apps.api.schemas import MarketRegimeOut, QuoteOut
from data.ingestion.provider import MarketDataProvider
from models.market_regime import MarketRegimeObservation

router = APIRouter(tags=["market"])


@router.get("/market/regime", response_model=MarketRegimeOut)
def get_latest_regime(session: Session = Depends(get_session)) -> MarketRegimeOut:
    row = session.scalars(
        select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No market regime observations recorded yet")
    return MarketRegimeOut(
        observed_at=row.observed_at,
        scope=row.scope,
        trend_regime=row.regime,
        volatility_regime=row.volatility_regime,
        risk_regime=row.risk_regime,
    )


@router.get("/market/{ticker}", response_model=QuoteOut)
def get_market_quote(
    ticker: str, market_data: MarketDataProvider = Depends(get_market_data)
) -> QuoteOut:
    quote = market_data.get_quote(ticker)
    return QuoteOut(
        ticker=quote.ticker,
        price=quote.price,
        change=quote.change,
        change_percent=quote.change_percent,
        volume=quote.volume,
        as_of=quote.as_of,
        source=quote.source,
    )
