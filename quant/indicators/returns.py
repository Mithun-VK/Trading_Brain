"""Returns, volatility, and drawdown -- shared by the technical and
performance/risk categories (Phase 5 lists max drawdown under both).
"""

from __future__ import annotations

import math
import statistics


def simple_returns(values: list[float]) -> list[float]:
    return [values[i] / values[i - 1] - 1 for i in range(1, len(values))]


def log_returns(values: list[float]) -> list[float]:
    return [math.log(values[i] / values[i - 1]) for i in range(1, len(values))]


def volatility(returns: list[float], annualize: bool = True, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    stdev = statistics.stdev(returns)
    return stdev * math.sqrt(periods_per_year) if annualize else stdev


def max_drawdown(values: list[float]) -> float:
    """Largest peak-to-trough decline, as a negative fraction (e.g. -0.23 for -23%)."""
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = (v - peak) / peak if peak else 0.0
        worst = min(worst, drawdown)
    return worst
