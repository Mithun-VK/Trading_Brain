from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Position(Base, TimestampMixin):
    """Current/historical portfolio holding. Derived from one or more trades
    but tracked separately so portfolio state can be queried without
    re-aggregating the full trade history each time.
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6))
    avg_price: Mapped[float] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|closed
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
