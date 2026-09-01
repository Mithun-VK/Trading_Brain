"""Portfolio/trade performance statistics. Rule 12 applies to every caller
of this module: never present these as a guarantee of future results, and
never claim statistical significance a sample size does not support
(see brain/review, Phase 10).
"""

from __future__ import annotations

import math
import statistics


def total_return(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2 or equity_curve[0] == 0:
        return 0.0
    return equity_curve[-1] / equity_curve[0] - 1


def cagr(equity_curve: list[float], periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    years = (len(equity_curve) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    ratio = equity_curve[-1] / equity_curve[0]
    if ratio <= 0:
        return -1.0
    return ratio ** (1 / years) - 1


def sharpe_ratio(
    returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> float:
    if len(returns) < 2:
        return 0.0
    target = risk_free_rate / periods_per_year
    excess = [r - target for r in returns]
    stdev = statistics.stdev(excess)
    if stdev == 0:
        return 0.0
    return (statistics.mean(excess) / stdev) * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> float:
    if len(returns) < 2:
        return 0.0
    target = risk_free_rate / periods_per_year
    excess = [r - target for r in returns]
    downside = [min(0.0, r) for r in excess]
    downside_dev = math.sqrt(sum(d**2 for d in downside) / len(downside))
    if downside_dev == 0:
        return 0.0
    return (statistics.mean(excess) / downside_dev) * math.sqrt(periods_per_year)


def win_rate(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    return sum(1 for p in trade_pnls if p > 0) / len(trade_pnls)


def profit_factor(trade_pnls: list[float]) -> float:
    gross_profit = sum(p for p in trade_pnls if p > 0)
    gross_loss = abs(sum(p for p in trade_pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def expectancy(trade_pnls: list[float]) -> float:
    return statistics.mean(trade_pnls) if trade_pnls else 0.0


def average_winner(trade_pnls: list[float]) -> float:
    winners = [p for p in trade_pnls if p > 0]
    return statistics.mean(winners) if winners else 0.0


def average_loser(trade_pnls: list[float]) -> float:
    losers = [p for p in trade_pnls if p < 0]
    return statistics.mean(losers) if losers else 0.0
