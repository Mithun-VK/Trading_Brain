from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from data.storage.regime_repository import save_regime_observation
from models.base import Base
from quant.regime.models import MarketRegime, RegimeObservation


def test_save_regime_observation_persists_all_axes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observation = RegimeObservation(
        observed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        trend_regime=MarketRegime.BULLISH,
        volatility_regime=MarketRegime.LOW_VOLATILITY,
        risk_regime=MarketRegime.RISK_ON,
        detail={"sma_short": 100.0, "annualized_volatility": 0.1},
    )

    with Session(engine) as session:
        row = save_regime_observation(session, observation)
        session.commit()

        assert row.regime == "BULLISH"
        assert row.volatility_regime == "LOW_VOLATILITY"
        assert row.risk_regime == "RISK_ON"
        assert row.detail["sma_short"] == 100.0
