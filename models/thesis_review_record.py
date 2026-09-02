from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ThesisReviewRecord(Base):
    """One recorded thesis assessment transition.

    The Obsidian note holds the narrative audit trail (Rule 9); this table
    holds the same transitions in queryable form, which is what makes
    "time to invalidation" and thesis accuracy *measurable* rather than
    approximated from a single current-state field.
    """

    __tablename__ = "thesis_review_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)
    previous_assessment: Mapped[str] = mapped_column(String(32))
    assessment: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    reasoning: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
