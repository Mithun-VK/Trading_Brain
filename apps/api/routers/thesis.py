from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.ai_dependencies import get_thesis_llm
from apps.api.dependencies import (
    get_knowledge_store,
    get_market_data,
    get_session,
)
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas import ThesisOut
from brain.market.context_assembler import ContextAssembler
from brain.thesis.schemas import ThesisReview
from brain.thesis.thesis_agent import ThesisAgent
from data.ingestion.provider import MarketDataProvider
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.thesis import Thesis

router = APIRouter(tags=["thesis"])


def _get_active_thesis_or_404(session: Session, asset_id: int, ticker: str) -> Thesis:
    thesis = session.scalars(
        select(Thesis)
        .where(Thesis.asset_id == asset_id, Thesis.status == "active")
        .order_by(Thesis.updated_at.desc())
    ).first()
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"No active thesis for {ticker!r}")
    return thesis


@router.get("/thesis/{ticker}", response_model=ThesisOut)
def get_thesis(ticker: str, session: Session = Depends(get_session)) -> ThesisOut:
    asset = get_asset_or_404(session, ticker)
    thesis = _get_active_thesis_or_404(session, asset.id, ticker)
    return ThesisOut(
        id=thesis.id,
        ticker=ticker,
        title=thesis.title,
        status=thesis.status,
        current_assessment=thesis.current_assessment,
        conviction=thesis.conviction,
        time_horizon=thesis.time_horizon,
        last_reviewed_at=thesis.last_reviewed_at,
    )


@router.post("/thesis/{ticker}/review", response_model=ThesisReview)
def review_thesis(
    ticker: str,
    session: Session = Depends(get_session),
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store),
    market_data: MarketDataProvider = Depends(get_market_data),
    llm_provider: LLMProvider = Depends(get_thesis_llm),
) -> ThesisReview:
    asset = get_asset_or_404(session, ticker)
    thesis = _get_active_thesis_or_404(session, asset.id, ticker)

    assembler = ContextAssembler(knowledge_store, session, market_data)
    agent = ThesisAgent(assembler, llm_provider, knowledge_store, session)
    review = agent.review_and_apply(thesis, asset)
    session.commit()
    return review
