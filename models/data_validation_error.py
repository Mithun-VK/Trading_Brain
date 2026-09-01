from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DataValidationError(Base):
    """A rejected or suspicious bar recorded by
    `data.normalization.validation`. Kept so bad vendor data is auditable
    after the fact rather than silently dropped.
    """

    __tablename__ = "data_validation_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    interval: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="error")
    message: Mapped[str] = mapped_column(Text)
    bar_ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
