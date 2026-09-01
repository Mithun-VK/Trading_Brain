"""Position sizing and portfolio risk. Deterministic (Rule 2) -- these
numbers gate what a human is allowed to act on; Claude never computes them.
"""

from __future__ import annotations


def position_size(
    account_equity: float, risk_per_trade_pct: float, entry_price: float, stop_price: float
) -> float:
    """Shares/units to buy so that a stop-out risks exactly
    `account_equity * risk_per_trade_pct`.
    """
    if entry_price == stop_price:
        raise ValueError("entry_price and stop_price must differ")
    per_share_risk = abs(entry_price - stop_price)
    return risk_amount(account_equity, risk_per_trade_pct) / per_share_risk


def risk_amount(account_equity: float, risk_per_trade_pct: float) -> float:
    return account_equity * risk_per_trade_pct


def r_multiple(
    entry_price: float, stop_price: float, exit_price: float, direction: str = "long"
) -> float:
    """PnL expressed in units of initial risk (1R = the entry-to-stop distance)."""
    per_share_risk = abs(entry_price - stop_price)
    if per_share_risk == 0:
        raise ValueError("entry_price and stop_price must differ")
    if direction == "long":
        pnl_per_share = exit_price - entry_price
    elif direction == "short":
        pnl_per_share = entry_price - exit_price
    else:
        raise ValueError("direction must be 'long' or 'short'")
    return pnl_per_share / per_share_risk


def portfolio_exposure(position_values: list[float], account_equity: float) -> float:
    """Gross exposure as a fraction of account equity (e.g. 0.65 = 65% deployed)."""
    if account_equity == 0:
        raise ValueError("account_equity must be non-zero")
    return sum(position_values) / account_equity
