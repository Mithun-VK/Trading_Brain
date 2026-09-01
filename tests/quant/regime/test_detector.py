from __future__ import annotations

import datetime as dt
import math

from quant.regime.detector import MarketRegimeDetector
from quant.regime.models import MarketRegime

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _uptrend(n: int = 250) -> list[float]:
    return [100 + i * 0.5 for i in range(n)]


def _downtrend(n: int = 250) -> list[float]:
    return [300 - i * 0.5 for i in range(n)]


def _sideways(n: int = 250) -> list[float]:
    # Slow, small-amplitude oscillation: raw slope stays well under the
    # detector's default threshold (~0.05 in absolute terms here) at every
    # phase of the cycle, so this is reliably SIDEWAYS regardless of `n`.
    return [100 + 2 * math.sin(i / 100) for i in range(n)]


def test_bullish_low_volatility_trend_is_risk_on() -> None:
    detector = MarketRegimeDetector()

    observation = detector.detect(_uptrend(), observed_at=NOW)

    assert observation.trend_regime is MarketRegime.BULLISH
    assert observation.volatility_regime is MarketRegime.LOW_VOLATILITY
    assert observation.risk_regime is MarketRegime.RISK_ON


def test_bearish_trend_detected() -> None:
    detector = MarketRegimeDetector()

    observation = detector.detect(_downtrend(), observed_at=NOW)

    assert observation.trend_regime is MarketRegime.BEARISH


def test_sideways_trend_detected() -> None:
    detector = MarketRegimeDetector()

    observation = detector.detect(_sideways(), observed_at=NOW)

    assert observation.trend_regime is MarketRegime.SIDEWAYS


def test_insufficient_history_is_unknown() -> None:
    detector = MarketRegimeDetector()

    observation = detector.detect([100.0], observed_at=NOW)

    assert observation.trend_regime is MarketRegime.UNKNOWN
    assert observation.volatility_regime is MarketRegime.UNKNOWN
    assert observation.risk_regime is MarketRegime.UNKNOWN


def test_high_volatility_detected() -> None:
    detector = MarketRegimeDetector()
    closes = _sideways(n=230) + [100 * (1.1 if i % 2 == 0 else 0.9) for i in range(25)]

    observation = detector.detect(closes, observed_at=NOW)

    assert observation.volatility_regime is MarketRegime.HIGH_VOLATILITY


def test_breadth_determines_risk_regime_when_trend_vol_combo_is_inconclusive() -> None:
    detector = MarketRegimeDetector()
    closes = _sideways()

    risk_on = detector.detect(closes, observed_at=NOW, breadth=0.6)
    risk_off = detector.detect(closes, observed_at=NOW, breadth=0.3)
    unclear = detector.detect(closes, observed_at=NOW, breadth=0.5)

    assert risk_on.risk_regime is MarketRegime.RISK_ON
    assert risk_off.risk_regime is MarketRegime.RISK_OFF
    assert unclear.risk_regime is MarketRegime.UNKNOWN


def test_detail_contains_diagnostic_values() -> None:
    detector = MarketRegimeDetector()

    observation = detector.detect(_uptrend(), observed_at=NOW, breadth=0.7)

    assert observation.detail["sma_short"] is not None
    assert observation.detail["sma_long"] is not None
    assert observation.detail["trend_slope"] is not None
    assert observation.detail["annualized_volatility"] is not None
    assert observation.detail["breadth"] == 0.7
