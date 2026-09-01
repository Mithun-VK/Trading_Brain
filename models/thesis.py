from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Thesis(Base, TimestampMixin):
    """Metadata + pointer for an Investment Thesis note. `current_assessment`
    mirrors brain.thesis.thesis_agent's ThesisAssessment enum
    (THESIS_INTACT/STRENGTHENED/WEAKENED/INVALIDATED/INSUFFICIENT_EVIDENCE);
    every change to it must correspond to a new dated entry in the note's
    "Historical Changes" section (Rule 9) — never a silent overwrite.
    """

    __tablename__ = "theses"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    current_assessment: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_EVIDENCE")
    conviction: Mapped[str | None] = mapped_column(String(16))
    time_horizon: Mapped[str | None] = mapped_column(String(32))
    obsidian_note_path: Mapped[str | None] = mapped_column(String(512))
    last_reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
