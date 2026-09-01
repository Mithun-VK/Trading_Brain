"""Market regime types. Descriptive classifications only -- they describe
what the rules observed in the data, never a forecast (see Critical Design
Rules in docs/architecture.md: "do not claim these regimes are predictive").
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum


class MarketRegime(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeObservation:
    observed_at: dt.datetime
    trend_regime: MarketRegime
    volatility_regime: MarketRegime
    risk_regime: MarketRegime
    detail: dict[str, float | None] = field(default_factory=dict)
