from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas import AssetOut

router = APIRouter(tags=["assets"])


@router.get("/assets/{ticker}", response_model=AssetOut)
def get_asset(ticker: str, session: Session = Depends(get_session)) -> AssetOut:
    asset = get_asset_or_404(session, ticker)
    return AssetOut(
        ticker=asset.ticker,
        exchange=asset.exchange,
        asset_type=asset.asset_type,
        name=asset.name,
        currency=asset.currency,
        sector=asset.company.sector if asset.company else None,
        industry=asset.company.industry if asset.company else None,
    )
