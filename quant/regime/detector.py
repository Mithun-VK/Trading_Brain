"""Rule-based market regime classification.

Every threshold lives in `RegimeDetectorConfig` so the rules are
configurable, not hard-coded. Classification degrades to `UNKNOWN` whenever
there isn't enough history to evaluate a rule confidently -- this module
never guesses.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from quant.indicators.moving_average import sma
from quant.indicators.returns import simple_returns, volatility
from quant.regime.models import MarketRegime, RegimeObservation


@dataclass(frozen=True)
class RegimeDetectorConfig:
    trend_short_period: int = 50
    trend_long_period: int = 200
    trend_slope_window: int = 20
    trend_slope_threshold: float = 0.0005  # ~0.05%/period, normalized by price

    volatility_window: int = 20
    volatility_threshold: float = 0.20  # annualized stdev

    breadth_risk_on_threshold: float = 0.55
    breadth_risk_off_threshold: float = 0.45


class MarketRegimeDetector:
    def __init__(self, config: RegimeDetectorConfig | None = None) -> None:
        self.config = config or RegimeDetectorConfig()

    def detect(
        self,
        closes: list[float],
        observed_at: dt.datetime,
        breadth: float | None = None,
    ) -> RegimeObservation:
        detail: dict[str, float | None] = {}

        trend_regime = self._classify_trend(closes, detail)
        volatility_regime = self._classify_volatility(closes, detail)
        risk_regime = self._classify_risk(trend_regime, volatility_regime, breadth, detail)

        detail["breadth"] = breadth
        return RegimeObservation(
            observed_at=observed_at,
            trend_regime=trend_regime,
            volatility_regime=volatility_regime,
            risk_regime=risk_regime,
            detail=detail,
        )

    def _classify_trend(
        self, closes: list[float], detail: dict[str, float | None]
    ) -> MarketRegime:
        cfg = self.config
        if len(closes) < cfg.trend_long_period:
            detail["sma_short"] = None
            detail["sma_long"] = None
            detail["trend_slope"] = None
            return MarketRegime.UNKNOWN

        price = closes[-1]
        sma_short = sma(closes, cfg.trend_short_period)[-1]
        sma_long = sma(closes, cfg.trend_long_period)[-1]
        slope = _normalized_slope(closes[-cfg.trend_slope_window :])
        detail["sma_short"] = sma_short
        detail["sma_long"] = sma_long
        detail["trend_slope"] = slope

        if sma_short is None or sma_long is None or slope is None:
            return MarketRegime.UNKNOWN

        if price > sma_short > sma_long and slope > cfg.trend_slope_threshold:
            return MarketRegime.BULLISH
        if price < sma_short < sma_long and slope < -cfg.trend_slope_threshold:
            return MarketRegime.BEARISH
        return MarketRegime.SIDEWAYS

    def _classify_volatility(
        self, closes: list[float], detail: dict[str, float | None]
    ) -> MarketRegime:
        cfg = self.config
        window = closes[-(cfg.volatility_window + 1) :]
        if len(window) < 2:
            detail["annualized_volatility"] = None
            return MarketRegime.UNKNOWN

        returns = simple_returns(window)
        annualized_vol = volatility(returns, annualize=True)
        detail["annualized_volatility"] = annualized_vol

        if annualized_vol >= cfg.volatility_threshold:
            return MarketRegime.HIGH_VOLATILITY
        return MarketRegime.LOW_VOLATILITY

    def _classify_risk(
        self,
        trend_regime: MarketRegime,
        volatility_regime: MarketRegime,
        breadth: float | None,
        detail: dict[str, float | None],
    ) -> MarketRegime:
        cfg = self.config
        is_bullish = trend_regime is MarketRegime.BULLISH
        is_bearish = trend_regime is MarketRegime.BEARISH
        is_calm = volatility_regime is MarketRegime.LOW_VOLATILITY
        is_turbulent = volatility_regime is MarketRegime.HIGH_VOLATILITY

        if is_bullish and is_calm:
            return MarketRegime.RISK_ON
        if is_bearish and is_turbulent:
            return MarketRegime.RISK_OFF

        if breadth is not None:
            if breadth >= cfg.breadth_risk_on_threshold:
                return MarketRegime.RISK_ON
            if breadth <= cfg.breadth_risk_off_threshold:
                return MarketRegime.RISK_OFF

        return MarketRegime.UNKNOWN


def _normalized_slope(values: list[float]) -> float | None:
    """Least-squares slope of `values` against period index, normalized by
    the window's mean value so it's comparable across price levels.
    """
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    if mean_y == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return (numerator / denominator) / mean_y
