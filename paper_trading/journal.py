"""Trade journal integration.

Paper transactions become `Trade` rows, so the Phase 11 Trade Journal
Review Agent analyses simulated trades with exactly the machinery it uses
for real ones -- one journal, one review path.

Honesty rule that shapes this module: an R-multiple requires a stop. When a
paper trade was opened without one, `r_multiple` stays NULL rather than
being back-fitted from the exit price. The review agent already excludes
trades without an R-multiple, so a missing stop quietly reduces the sample
instead of inflating it with invented risk.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.paper_portfolio import PaperPortfolio
from models.trade import Trade
from quant.performance.risk import r_multiple


def _current_regime(session: Session) -> str | None:
    observation = session.scalars(
        select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
    ).first()
    return observation.regime if observation else None


def open_trade_record(
    session: Session,
    portfolio: PaperPortfolio,
    asset: Asset,
    quantity: float,
    entry_price: float,
    opened_at: dt.datetime,
    stop_price: float | None = None,
    target_price: float | None = None,
    timeframe: str = "1d",
    strategy_id: int | None = None,
) -> Trade:
    """Journal the opening of a paper position."""
    risk_amount = (
        abs(entry_price - stop_price) * quantity if stop_price is not None else None
    )
    trade = Trade(
        asset_id=asset.id,
        strategy_id=strategy_id,
        direction="long",
        timeframe=timeframe,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        risk_amount=risk_amount,
        position_size=quantity,
        status="open",
        market_regime=_current_regime(session),
        opened_at=opened_at,
    )
    session.add(trade)
    session.flush()
    return trade


def close_trade_record(
    session: Session,
    trade: Trade,
    exit_price: float,
    closed_at: dt.datetime,
) -> Trade:
    """Journal the closing of a paper position.

    `r_multiple` is computed only when the trade recorded a stop; otherwise
    it stays NULL (see the module docstring).
    """
    trade.status = "closed"
    trade.closed_at = closed_at

    entry = float(trade.entry_price)
    if trade.stop_price is not None and float(trade.stop_price) != entry:
        trade.r_multiple = round(
            r_multiple(
                entry_price=entry,
                stop_price=float(trade.stop_price),
                exit_price=exit_price,
                direction=trade.direction,
            ),
            4,
        )

    pnl = (exit_price - entry) * float(trade.position_size)
    if pnl > 0:
        trade.result = "win"
    elif pnl < 0:
        trade.result = "loss"
    else:
        trade.result = "breakeven"

    session.flush()
    return trade


def find_open_trade(session: Session, asset: Asset) -> Trade | None:
    return session.scalars(
        select(Trade)
        .where(Trade.asset_id == asset.id, Trade.status == "open")
        .order_by(Trade.opened_at.desc())
    ).first()


def journal_paper_fill(
    session: Session,
    portfolio: PaperPortfolio,
    asset: Asset,
    side: str,
    quantity: float,
    price: float,
    executed_at: dt.datetime,
    stop_price: float | None = None,
    remaining_quantity: float | None = None,
) -> Trade | None:
    """Reflect one paper fill in the trade journal.

    A buy opens a trade record (or leaves the existing open one alone, since
    averaging into a position is still one trade). A sell closes it only
    when the position went flat -- a partial trim is not a completed trade.
    """
    if side == "buy":
        existing = find_open_trade(session, asset)
        if existing is not None:
            return existing
        return open_trade_record(
            session, portfolio, asset, quantity, price, executed_at, stop_price=stop_price
        )

    if side == "sell":
        open_trade = find_open_trade(session, asset)
        if open_trade is None:
            return None
        if remaining_quantity is not None and remaining_quantity > 0:
            return open_trade  # partial exit: the trade is still running
        return close_trade_record(session, open_trade, price, executed_at)

    return None
