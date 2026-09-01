from __future__ import annotations

from sqlalchemy.orm import Session

from models.market_regime import MarketRegimeObservation
from quant.regime.models import RegimeObservation


def save_regime_observation(
    session: Session, observation: RegimeObservation, scope: str = "broad_market"
) -> MarketRegimeObservation:
    row = MarketRegimeObservation(
        observed_at=observation.observed_at,
        scope=scope,
        regime=observation.trend_regime.value,
        volatility_regime=observation.volatility_regime.value,
        risk_regime=observation.risk_regime.value,
        detail=observation.detail,
    )
    session.add(row)
    session.flush()
    return row
