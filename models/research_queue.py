from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.asset import Asset


class ResearchQueueEntry(Base, TimestampMixin):
    """A deterministically-surfaced reason to research something.

    Rows are created by `ResearchIntelligenceEngine`, worked highest-score
    first, and carry the full component breakdown so a queue position is
    always explainable rather than an opaque ranking.
    """

    __tablename__ = "research_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    change_type: Mapped[str] = mapped_column(String(32), index=True)
    # pending | in_progress | done | dismissed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)

    score: Mapped[float] = mapped_column(Numeric(6, 4), index=True)
    importance: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    novelty: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    portfolio_impact: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    watchlist_relevance: Mapped[float] = mapped_column(Numeric(6, 4), default=0)

    reasons: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text)

    detected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    research_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_documents.id")
    )

    asset: Mapped[Asset] = relationship("Asset")
