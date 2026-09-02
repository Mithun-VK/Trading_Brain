"""Research queue API.

Always ordered by priority score, since working the queue out of order
defeats the point of scoring it. `process` runs the Research Agent on a
queued item and closes the entry; `dismiss` closes it without research and
records why -- a dismissal stays auditable rather than silent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies import (
    get_knowledge_store,
    get_llm_provider,
    get_market_data,
    get_session,
)
from apps.api.schemas_v2 import QueueDismissIn, ResearchQueueOut
from brain.market.context_assembler import ContextAssembler
from brain.research.research_agent import ResearchAgent
from brain.research.schemas import ResearchAnalysis
from data.ingestion.provider import MarketDataProvider
from data.storage.research_queue_repository import (
    STATUS_PENDING,
    dismiss,
    get_queue,
    mark_done,
)
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.asset import Asset
from models.research_queue import ResearchQueueEntry

router = APIRouter(tags=["research-queue"])


def _to_out(entry: ResearchQueueEntry) -> ResearchQueueOut:
    return ResearchQueueOut(
        id=entry.id,
        asset_id=entry.asset_id,
        ticker=entry.ticker,
        change_type=entry.change_type,
        status=entry.status,
        score=float(entry.score),
        importance=float(entry.importance),
        novelty=float(entry.novelty),
        portfolio_impact=float(entry.portfolio_impact),
        watchlist_relevance=float(entry.watchlist_relevance),
        reasons=list(entry.reasons or []),
        detail=dict(entry.detail or {}),
        detected_at=entry.detected_at,
        processed_at=entry.processed_at,
        research_document_id=entry.research_document_id,
        note=entry.note,
    )


def _get_or_404(session: Session, entry_id: int) -> ResearchQueueEntry:
    entry = session.get(ResearchQueueEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No research queue entry {entry_id}")
    return entry


@router.get("/research/queue", response_model=list[ResearchQueueOut])
def list_queue(
    status: str = STATUS_PENDING,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[ResearchQueueOut]:
    """Highest priority first (ties broken by oldest detection)."""
    return [_to_out(e) for e in get_queue(session, status=status, limit=limit)]


@router.get("/research/queue/{entry_id}", response_model=ResearchQueueOut)
def get_entry(entry_id: int, session: Session = Depends(get_session)) -> ResearchQueueOut:
    return _to_out(_get_or_404(session, entry_id))


@router.post("/research/queue/{entry_id}/process", response_model=ResearchAnalysis)
def process_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    knowledge_store: KnowledgeStore = Depends(get_knowledge_store),
    market_data: MarketDataProvider = Depends(get_market_data),
    llm_provider: LLMProvider = Depends(get_llm_provider),
) -> ResearchAnalysis:
    """Run the Research Agent for this entry and close it."""
    entry = _get_or_404(session, entry_id)
    if entry.status in ("done", "dismissed"):
        raise HTTPException(
            status_code=409, detail=f"Entry {entry_id} is already {entry.status}"
        )

    asset = session.get(Asset, entry.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Entry references a missing asset")

    assembler = ContextAssembler(knowledge_store, session, market_data)
    agent = ResearchAgent(assembler, llm_provider, knowledge_store, session)

    analysis = agent.research(asset.ticker, asset=asset)
    note_path = agent.publish(analysis, asset=asset)

    from models.research_document import ResearchDocument

    document = (
        session.query(ResearchDocument)
        .filter(ResearchDocument.obsidian_note_path == note_path)
        .order_by(ResearchDocument.id.desc())
        .first()
    )
    mark_done(session, entry, research_document_id=document.id if document else None)
    session.commit()
    return analysis


@router.post("/research/queue/{entry_id}/dismiss", response_model=ResearchQueueOut)
def dismiss_entry(
    entry_id: int,
    payload: QueueDismissIn | None = None,
    session: Session = Depends(get_session),
) -> ResearchQueueOut:
    entry = _get_or_404(session, entry_id)
    if entry.status in ("done", "dismissed"):
        raise HTTPException(
            status_code=409, detail=f"Entry {entry_id} is already {entry.status}"
        )

    dismiss(session, entry, note=payload.note if payload else None)
    session.commit()
    return _to_out(entry)
