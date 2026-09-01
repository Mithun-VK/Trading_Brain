from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.asset import Asset


def get_asset_or_404(session: Session, ticker: str) -> Asset:
    asset = session.scalars(select(Asset).where(Asset.ticker == ticker)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker!r}")
    return asset
