from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.asset import Asset
    from models.strategy import Strategy


class Trade(Base, TimestampMixin):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # "long" | "short"
    timeframe: Mapped[str] = mapped_column(String(16))
    entry_price: Mapped[float] = mapped_column(Numeric(18, 6))
    # Nullable: a paper position may be opened without a defined stop.
    # Inventing one would fabricate risk that was never taken.
    stop_price: Mapped[float | None] = mapped_column(Numeric(18, 6))
    target_price: Mapped[float | None] = mapped_column(Numeric(18, 6))
    risk_amount: Mapped[float | None] = mapped_column(Numeric(18, 6))
    position_size: Mapped[float] = mapped_column(Numeric(18, 6))
    r_multiple: Mapped[float | None] = mapped_column(Numeric(10, 4))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|closed
    result: Mapped[str | None] = mapped_column(String(16))  # win|loss|breakeven
    market_regime: Mapped[str | None] = mapped_column(String(32))
    obsidian_note_path: Mapped[str | None] = mapped_column(String(512))
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    strategy: Mapped[Strategy | None] = relationship("Strategy")
    asset: Mapped[Asset] = relationship("Asset")
