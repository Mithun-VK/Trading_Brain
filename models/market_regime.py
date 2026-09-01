from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MarketRegimeObservation(Base):
    """A point-in-time regime classification produced by
    `quant.regime.detector.MarketRegimeDetector`. Descriptive, not predictive
    (see Critical Design Rules) — `regime`/`volatility_regime`/`risk_regime`
    store `quant.regime.models.MarketRegime` values as strings.
    """

    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(primary_key=True)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    scope: Mapped[str] = mapped_column(String(64), default="broad_market")
    regime: Mapped[str] = mapped_column(String(32))
    volatility_regime: Mapped[str] = mapped_column(String(32))
    risk_regime: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
