from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class LearningReview(Base):
    """A periodic self-assessment, stored in PostgreSQL and mirrored to
    Obsidian. Unique per (kind, period_start) so re-running a month's review
    refreshes it rather than accumulating duplicates.
    """

    __tablename__ = "learning_reviews"
    __table_args__ = (
        UniqueConstraint("kind", "period_start", name="uq_learning_reviews_kind_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # monthly|quarterly|annual
    period_start: Mapped[dt.date] = mapped_column(Date, index=True)
    period_end: Mapped[dt.date] = mapped_column(Date)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text)
    obsidian_note_path: Mapped[str | None] = mapped_column(String(512))
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
