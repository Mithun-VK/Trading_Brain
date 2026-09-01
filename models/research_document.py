from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ResearchDocument(Base):
    """Metadata + pointer for a Research Agent (or manual) output. The full
    rendered content lives in Obsidian (`obsidian_note_path`); this row makes
    it queryable/joinable from PostgreSQL without duplicating the vault.
    """

    __tablename__ = "research_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    obsidian_note_path: Mapped[str | None] = mapped_column(String(512))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))  # 0.000-1.000
    source: Mapped[str] = mapped_column(String(32))  # "claude" | "manual"
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
