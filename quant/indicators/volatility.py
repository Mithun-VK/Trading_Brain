"""ATR and Bollinger Bands."""

from __future__ import annotations

import statistics

from quant.indicators.moving_average import sma


def true_range(high: list[float], low: list[float], close: list[float]) -> list[float]:
    n = len(close)
    tr: list[float] = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    return tr


def atr(
    high: list[float], low: list[float], close: list[float], period: int = 14
) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")

    tr = true_range(high, low, close)
    n = len(close)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    prev = sum(tr[:period]) / period
    result[period - 1] = prev
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        result[i] = prev
    return result


def bollinger_bands(
    values: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (upper, middle, lower)."""
    middle = sma(values, period)
    n = len(values)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(n):
        mid = middle[i]
        if mid is not None:
            window = values[i - period + 1 : i + 1]
            std = statistics.pstdev(window)
            upper[i] = mid + num_std * std
            lower[i] = mid - num_std * std
    return upper, middle, lower
