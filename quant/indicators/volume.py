"""VWAP. Cumulative over whatever series is passed in -- for an intraday
session VWAP, pass only that session's bars; this function does not reset
on day boundaries itself.
"""

from __future__ import annotations


def vwap(high: list[float], low: list[float], close: list[float], volume: list[int]) -> list[float]:
    n = len(close)
    result: list[float] = [0.0] * n
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for i in range(n):
        typical_price = (high[i] + low[i] + close[i]) / 3
        cumulative_pv += typical_price * volume[i]
        cumulative_volume += volume[i]
        result[i] = cumulative_pv / cumulative_volume if cumulative_volume else 0.0
    return result
