"""Paper trading API.

**Simulations only.** Creating or closing a paper position requires
`confirm: true` in the request body — an explicit human act, refused
otherwise (Rule 7). Nothing here reaches a broker (Rule 8).

Every operation goes through the existing domain services
(`data.storage.portfolio_repository` for accounting, `paper_trading.journal`
for the trade record), so a position opened here is indistinguishable from
one opened by an approved proposal, and the Learning Engine sees both.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas_v2 import (
    PaperTradeCloseIn,
    PaperTradeCreate,
    PaperTradeOut,
    PaperTradePerformanceOut,
)
from data.storage.portfolio_repository import record_buy, record_sell
from models.asset import Asset
from models.signal import Signal
from models.trade import Trade
from paper_trading.journal import close_trade_record, open_trade_record
from paper_trading.service import PortfolioNotFoundError, holding_period_days, resolve_portfolio
from quant.indicators.returns import max_drawdown
from quant.performance.stats import (
    average_loser,
    average_winner,
    expectancy,
    profit_factor,
    win_rate,
)

router = APIRouter(tags=["paper-trades"])

MIN_SAMPLE_SIZE = 10

CONFIRMATION_REQUIRED = (
    "Explicit confirmation is required: set confirm=true. A paper position is "
    "never opened or closed as a side effect (Rule 7)."
)


def _to_out(session: Session, trade: Trade, portfolio_name: str = "") -> PaperTradeOut:
    asset = session.get(Asset, trade.asset_id)
    pnl = None
    if trade.status == "closed" and trade.result is not None:
        # PnL is reconstructed from the recorded R-multiple where a stop
        # existed; otherwise it stays None rather than being guessed.
        if trade.r_multiple is not None and trade.risk_amount is not None:
            pnl = round(float(trade.r_multiple) * float(trade.risk_amount), 6)

    return PaperTradeOut(
        id=trade.id,
        ticker=asset.ticker if asset else "",
        portfolio=portfolio_name,
        direction=trade.direction,
        status=trade.status,
        quantity=float(trade.position_size),
        entry_price=float(trade.entry_price),
        stop_price=float(trade.stop_price) if trade.stop_price is not None else None,
        target_price=float(trade.target_price) if trade.target_price is not None else None,
        risk_amount=float(trade.risk_amount) if trade.risk_amount is not None else None,
        r_multiple=float(trade.r_multiple) if trade.r_multiple is not None else None,
        result=trade.result,
        market_regime=trade.market_regime,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        holding_period_days=holding_period_days(trade),
        pnl=pnl,
        reasoning=trade.obsidian_note_path,
    )


def _resolve(session: Session, name: str | None):
    try:
        return resolve_portfolio(session, name)
    except PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/paper-trades", response_model=list[PaperTradeOut])
def list_paper_trades(
    status: str | None = None,
    ticker: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[PaperTradeOut]:
    query = select(Trade).order_by(Trade.opened_at.desc())
    if status:
        query = query.where(Trade.status == status)
    if ticker:
        asset = get_asset_or_404(session, ticker)
        query = query.where(Trade.asset_id == asset.id)
    return [_to_out(session, t) for t in session.scalars(query.limit(limit)).all()]


@router.get("/paper-trades/performance", response_model=PaperTradePerformanceOut)
def paper_trade_performance(
    session: Session = Depends(get_session),
) -> PaperTradePerformanceOut:
    """R-multiple statistics over closed trades.

    Trades without a recorded stop have no honest R-multiple and are
    excluded from scoring rather than assigned invented risk.
    """
    closed = list(session.scalars(select(Trade).where(Trade.status == "closed")).all())
    r_multiples = [float(t.r_multiple) for t in closed if t.r_multiple is not None]

    caveat = None
    if len(r_multiples) < MIN_SAMPLE_SIZE:
        caveat = (
            f"Sample size too small for statistical significance "
            f"(n={len(r_multiples)}, need {MIN_SAMPLE_SIZE})."
        )

    equity_curve: list[float] = []
    running = 0.0
    for r in r_multiples:
        running += r
        equity_curve.append(running)

    factor = profit_factor(r_multiples)
    return PaperTradePerformanceOut(
        trade_count=len(closed),
        scored_trades=len(r_multiples),
        win_rate=round(win_rate(r_multiples), 4),
        profit_factor=round(factor, 4) if factor != float("inf") else 0.0,
        expectancy_r=round(expectancy(r_multiples), 4),
        average_winner_r=round(average_winner(r_multiples), 4),
        average_loser_r=round(average_loser(r_multiples), 4),
        max_drawdown=round(max_drawdown(equity_curve), 4) if equity_curve else 0.0,
        is_significant=len(r_multiples) >= MIN_SAMPLE_SIZE,
        caveat=caveat,
    )


@router.get("/paper-trades/{trade_id}", response_model=PaperTradeOut)
def get_paper_trade(trade_id: int, session: Session = Depends(get_session)) -> PaperTradeOut:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"No paper trade with id {trade_id}")
    return _to_out(session, trade)


@router.post("/paper-trades", response_model=PaperTradeOut, status_code=201)
def open_paper_trade(
    payload: PaperTradeCreate, session: Session = Depends(get_session)
) -> PaperTradeOut:
    if not payload.confirm:
        raise HTTPException(status_code=422, detail=CONFIRMATION_REQUIRED)

    portfolio = _resolve(session, payload.portfolio)
    asset = get_asset_or_404(session, payload.ticker)

    if payload.signal_id is not None and session.get(Signal, payload.signal_id) is None:
        raise HTTPException(
            status_code=404, detail=f"No signal with id {payload.signal_id}"
        )

    now = dt.datetime.now(dt.UTC)
    try:
        record_buy(
            session, portfolio, asset,
            quantity=payload.quantity, price=payload.price,
            executed_at=now, note=payload.reasoning,
        )
    except Exception as exc:  # InsufficientCash / PortfolioError
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    trade = open_trade_record(
        session, portfolio, asset,
        quantity=payload.quantity, entry_price=payload.price, opened_at=now,
        stop_price=payload.stop_price, target_price=payload.target_price,
    )
    trade.obsidian_note_path = payload.reasoning
    session.commit()
    return _to_out(session, trade, portfolio.name)


@router.post("/paper-trades/{trade_id}/close", response_model=PaperTradeOut)
def close_paper_trade(
    trade_id: int, payload: PaperTradeCloseIn, session: Session = Depends(get_session)
) -> PaperTradeOut:
    if not payload.confirm:
        raise HTTPException(status_code=422, detail=CONFIRMATION_REQUIRED)

    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"No paper trade with id {trade_id}")
    if trade.status != "open":
        raise HTTPException(status_code=409, detail=f"Trade {trade_id} is already closed")

    asset = session.get(Asset, trade.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Trade references a missing asset")

    portfolio = _resolve(session, None)
    now = dt.datetime.now(dt.UTC)
    try:
        record_sell(
            session, portfolio, asset,
            quantity=float(trade.position_size), price=payload.price, executed_at=now,
        )
    except Exception as exc:  # InsufficientPosition / PortfolioError
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    close_trade_record(session, trade, exit_price=payload.price, closed_at=now)
    session.commit()
    return _to_out(session, trade, portfolio.name)
