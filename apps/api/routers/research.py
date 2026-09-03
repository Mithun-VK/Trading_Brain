from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.ai_dependencies import get_research_llm
from apps.api.dependencies import (
    get_knowledge_store,
    get_market_data,
    get_session,
)
from apps.api.routers._common import get_asset_or_404
from brain.market.context_assembler import ContextAssembler
from brain.research.research_agent import ResearchAgent
from brain.research.schemas import ResearchAnalysis
from data.ingestion.provider import MarketDataProvider
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore

router = APIRouter(tags=["research"])


@router.post("/research/{ticker}", response_model=ResearchAnalysis)
def create_research(
    ticker: str,
    session: Session = Depends(get_session),
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store),
    market_data: MarketDataProvider = Depends(get_market_data),
    llm_provider: LLMProvider = Depends(get_research_llm),
) -> ResearchAnalysis:
    asset = get_asset_or_404(session, ticker)
    assembler = ContextAssembler(knowledge_store, session, market_data)
    agent = ResearchAgent(assembler, llm_provider, knowledge_store, session)

    analysis = agent.research(ticker, asset=asset)
    agent.publish(analysis, asset=asset)
    session.commit()
    return analysis
