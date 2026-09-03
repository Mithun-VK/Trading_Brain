"""V4 — regime labelling, computed causally.

The whole value of a regime decomposition rests on one property: the label
at bar *t* must be computable from bars up to and including *t*, and from
nothing after. Get that wrong and the decomposition says "the strategy does
well in bull markets" when it actually means "the strategy does well on days
that later turned out to be part of a bull market" — which is not a fact you
can trade on.

So every label here is produced by a forward pass over a prefix of the
series. There is no smoothing, no centred window, and no backfill. A label
that cannot yet be determined is `UNKNOWN`, never the previous value carried
forward and never the eventual value filled back.

Nine states, from the V4 brief. The first three are the existing detector's
trend classes, reused rather than reimplemented so the experiment measures
the same maths the live path uses. The rest are computed here:

    momentum expansion / contraction  — is trend strength growing or decaying
    crisis                            — deep drawdown from the running peak
    recovery                          — rising out of a crisis, not yet whole

Crisis and recovery are deliberately *overriding* states: a bull-trending
label during a 25% drawdown is technically defensible and practically
useless.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from enum import StrEnum

from data.ingestion.schemas import PriceBar
from quant.regime.detector import MarketRegimeDetector, RegimeDetectorConfig
from quant.regime.models import MarketRegime


class Regime(StrEnum):
    """The nine states V4 asks for, plus UNKNOWN for "not yet determinable"."""

    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOL = "high_volatility"
    LOW_VOL = "low_volatility"
    MOMENTUM_EXPANSION = "momentum_expansion"
    MOMENTUM_CONTRACTION = "momentum_contraction"
    CRISIS = "crisis"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeConfig:
    """Thresholds, stated so the decomposition is interpretable.

    "Performance in a bull market" means nothing until you say what made it
    a bull market, so these values are part of the experiment record.
    """

    trend: RegimeDetectorConfig = None  # type: ignore[assignment]
    momentum_window: int = 20
    momentum_compare_window: int = 60
    crisis_drawdown: float = 0.15  # 15% off the running peak
    recovery_retrace: float = 0.50  # regained half the crisis loss
    min_bars: int = 200  # the trend detector needs its long SMA

    def __post_init__(self) -> None:
        if self.trend is None:
            object.__setattr__(self, "trend", RegimeDetectorConfig())


@dataclass(frozen=True)
class RegimeLabel:
    """What was knowable at this bar, and nothing else."""

    date: dt.date
    trend: Regime
    volatility: Regime
    momentum: Regime
    stress: Regime  # CRISIS, RECOVERY, or UNKNOWN when neither applies
    drawdown: float
    annualised_vol: float | None
    trend_slope: float | None

    @property
    def primary(self) -> Regime:
        """One label per bar for the headline decomposition.

        Stress overrides trend: a "bull" label during a 25% drawdown is
        technically defensible and practically useless.
        """
        if self.stress in (Regime.CRISIS, Regime.RECOVERY):
            return self.stress
        return self.trend

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "primary": str(self.primary),
            "trend": str(self.trend),
            "volatility": str(self.volatility),
            "momentum": str(self.momentum),
            "stress": str(self.stress),
            "drawdown": round(self.drawdown, 6),
            "annualised_vol": self.annualised_vol,
            "trend_slope": self.trend_slope,
        }


_TREND_MAP = {
    MarketRegime.BULLISH: Regime.BULL,
    MarketRegime.BEARISH: Regime.BEAR,
    MarketRegime.SIDEWAYS: Regime.SIDEWAYS,
    MarketRegime.UNKNOWN: Regime.UNKNOWN,
}
_VOL_MAP = {
    MarketRegime.HIGH_VOLATILITY: Regime.HIGH_VOL,
    MarketRegime.LOW_VOLATILITY: Regime.LOW_VOL,
    MarketRegime.UNKNOWN: Regime.UNKNOWN,
}


def _momentum_state(closes: list[float], config: RegimeConfig) -> Regime:
    """Is trend strength growing or decaying?

    Compares recent absolute momentum against its own longer-run average.
    Both are computed from the prefix, so this is causal.
    """
    short, long = config.momentum_window, config.momentum_compare_window
    if len(closes) < long + short:
        return Regime.UNKNOWN

    def abs_move(window: list[float]) -> float:
        if len(window) < 2 or window[0] == 0:
            return 0.0
        return abs((window[-1] - window[0]) / window[0])

    recent = abs_move(closes[-short:])
    prior_windows = [
        abs_move(closes[i - short : i]) for i in range(len(closes) - long, len(closes), short)
    ]
    prior = statistics.mean([w for w in prior_windows if w > 0] or [0.0])
    if prior == 0:
        return Regime.UNKNOWN
    return Regime.MOMENTUM_EXPANSION if recent > prior else Regime.MOMENTUM_CONTRACTION


def label_series(
    bars: list[PriceBar], config: RegimeConfig | None = None
) -> list[RegimeLabel]:
    """Label every bar using only the bars up to and including it.

    Implemented as an explicit forward pass rather than a vectorised
    calculation, because the vectorised version is where look-ahead creeps
    in: a rolling window that happens to be centred, or a fill that reaches
    backwards, produces labels that are correct in hindsight and unusable in
    practice.
    """
    config = config or RegimeConfig()
    detector = MarketRegimeDetector(config.trend)
    ordered = sorted(bars, key=lambda b: b.ts)
    closes: list[float] = []
    labels: list[RegimeLabel] = []

    peak = float("-inf")
    trough_after_peak = float("inf")
    in_crisis = False
    crisis_peak = 0.0

    for bar in ordered:
        closes.append(bar.close)
        price = bar.close

        # --- drawdown from the running peak (causal by construction) ---
        peak = max(peak, price)
        drawdown = (price - peak) / peak if peak > 0 else 0.0

        # --- crisis / recovery ---
        if not in_crisis and drawdown <= -config.crisis_drawdown:
            in_crisis = True
            crisis_peak = peak
            trough_after_peak = price
        elif in_crisis:
            trough_after_peak = min(trough_after_peak, price)
            lost = crisis_peak - trough_after_peak
            regained = price - trough_after_peak
            if lost > 0 and regained / lost >= config.recovery_retrace:
                in_crisis = False

        if in_crisis:
            stress = Regime.CRISIS
        elif drawdown < -0.05 and trough_after_peak != float("inf") and price > trough_after_peak:
            # Climbing out of a prior crisis but not yet back to the old high.
            stress = Regime.RECOVERY
        else:
            stress = Regime.UNKNOWN

        # --- trend and volatility, from the shared detector ---
        if len(closes) < config.min_bars:
            trend = Regime.UNKNOWN
            vol = Regime.UNKNOWN
            annualised = None
            slope = None
        else:
            observation = detector.detect(closes, observed_at=bar.ts)
            trend = _TREND_MAP.get(observation.trend_regime, Regime.UNKNOWN)
            vol = _VOL_MAP.get(observation.volatility_regime, Regime.UNKNOWN)
            annualised = observation.detail.get("annualized_volatility")
            slope = observation.detail.get("trend_slope")

        labels.append(
            RegimeLabel(
                date=bar.ts.date(),
                trend=trend,
                volatility=vol,
                momentum=_momentum_state(closes, config),
                stress=stress,
                drawdown=drawdown,
                annualised_vol=annualised,
                trend_slope=slope,
            )
        )

    return labels


def index_by_date(labels: list[RegimeLabel]) -> dict[dt.date, RegimeLabel]:
    return {label.date: label for label in labels}


def lookup(
    by_date: dict[dt.date, RegimeLabel], when: dt.date
) -> RegimeLabel | None:
    """The label in force on `when`.

    Falls back to the most recent *earlier* label when the date is not a
    trading day -- never a later one, which would be look-ahead in the one
    place it would be least visible.
    """
    if when in by_date:
        return by_date[when]
    earlier = [d for d in by_date if d < when]
    return by_date[max(earlier)] if earlier else None


def distribution(labels: list[RegimeLabel]) -> dict[str, int]:
    """How many bars fell in each primary regime. The denominator for every
    per-regime statistic, and the first thing to check when one looks
    surprising."""
    counts: dict[str, int] = {}
    for label in labels:
        key = str(label.primary)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
