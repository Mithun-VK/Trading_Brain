"""Trade *journaling* endpoints -- recording trades the human already made
or planned. Not broker execution: nothing here places an order (see the
hard guard in apps/api/main.py for Rule 8).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_knowledge_store, get_llm_provider, get_session
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas import TradeIn, TradeOut
from brain.review.review_agent import TradeJournalReviewAgent
from brain.review.schemas import JournalReview
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.strategy import Strategy
from models.trade import Trade

router = APIRouter(tags=["trades"])


def _to_trade_out(trade: Trade, ticker: str) -> TradeOut:
    return TradeOut(
        id=trade.id,
        ticker=ticker,
        direction=trade.direction,
        timeframe=trade.timeframe,
        entry_price=float(trade.entry_price),
        stop_price=float(trade.stop_price) if trade.stop_price is not None else None,
        target_price=float(trade.target_price) if trade.target_price is not None else None,
        risk_amount=float(trade.risk_amount) if trade.risk_amount is not None else None,
        position_size=float(trade.position_size),
        r_multiple=float(trade.r_multiple) if trade.r_multiple is not None else None,
        status=trade.status,
        result=trade.result,
        market_regime=trade.market_regime,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
    )


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    ticker: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> list[TradeOut]:
    query = select(Trade).order_by(Trade.opened_at.desc())
    if ticker:
        asset = get_asset_or_404(session, ticker)
        query = query.where(Trade.asset_id == asset.id)
    if status:
        query = query.where(Trade.status == status)

    trades = session.scalars(query).all()
    return [_to_trade_out(t, t.asset.ticker) for t in trades]


@router.post("/trades", response_model=TradeOut, status_code=201)
def create_trade(payload: TradeIn, session: Session = Depends(get_session)) -> TradeOut:
    asset = get_asset_or_404(session, payload.ticker)

    strategy_id = None
    if payload.strategy_name:
        strategy = session.scalars(
            select(Strategy).where(Strategy.name == payload.strategy_name)
        ).first()
        if strategy is None:
            strategy = Strategy(name=payload.strategy_name, rules={})
            session.add(strategy)
            session.flush()
        strategy_id = strategy.id

    trade = Trade(
        asset_id=asset.id,
        strategy_id=strategy_id,
        direction=payload.direction,
        timeframe=payload.timeframe,
        entry_price=payload.entry_price,
        stop_price=payload.stop_price,
        target_price=payload.target_price,
        risk_amount=payload.risk_amount,
        position_size=payload.position_size,
        market_regime=payload.market_regime,
        opened_at=payload.opened_at,
    )
    session.add(trade)
    session.commit()
    return _to_trade_out(trade, payload.ticker)


@router.post("/trades/{trade_id}/review", response_model=JournalReview)
def review_trade(
    trade_id: int,
    session: Session = Depends(get_session),
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> JournalReview:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"No trade with id {trade_id}")

    agent = TradeJournalReviewAgent(session, llm_provider, knowledge_store)
    review = agent.review([trade])
    agent.publish(review)
    session.commit()
    return review
