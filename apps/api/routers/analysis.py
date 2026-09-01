from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.dependencies import get_market_data, get_session
from apps.api.schemas import AnalysisOut
from brain.market.context_assembler import compute_quant_summary, get_latest_regime
from data.ingestion.provider import MarketDataProvider

router = APIRouter(tags=["analysis"])


@router.get("/analysis/{ticker}", response_model=AnalysisOut)
def get_analysis(
    ticker: str,
    session: Session = Depends(get_session),
    market_data: MarketDataProvider = Depends(get_market_data),
) -> AnalysisOut:
    return AnalysisOut(
        ticker=ticker,
        quant_summary=compute_quant_summary(market_data, ticker),
        market_regime=get_latest_regime(session),
    )
