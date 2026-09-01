from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.research.schemas import ResearchAnalysis
from models.asset import Asset
from models.research_document import ResearchDocument


def get_latest_research_document(session: Session, asset_id: int) -> ResearchDocument | None:
    return session.scalars(
        select(ResearchDocument)
        .where(ResearchDocument.asset_id == asset_id)
        .order_by(ResearchDocument.created_at.desc())
    ).first()


def save_research_document(
    session: Session, analysis: ResearchAnalysis, note_path: str, asset: Asset | None = None
) -> ResearchDocument:
    row = ResearchDocument(
        asset_id=asset.id if asset else None,
        title=f"Research: {analysis.ticker}",
        summary=analysis.summary,
        obsidian_note_path=note_path,
        confidence=analysis.confidence,
        source="claude",
    )
    session.add(row)
    session.flush()
    return row
