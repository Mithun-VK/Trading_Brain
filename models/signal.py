from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Signal(Base):
    """A deterministic output combining regime, quant, research and thesis
    state -- not a Claude output. Claude reasons over signals; it does not
    produce them (Rules 1/2).

    `category` holds a `brain.signals.schemas.SignalCategory` value. That
    enum contains no BUY/SELL/EXECUTE member, so this table structurally
    cannot store an execution instruction (Rules 7/8).
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64))  # e.g. "quant.indicators.rsi"
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

    # --- Phase 19: attention signals ---
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    reasoning: Mapped[str | None] = mapped_column(Text)
    # Structured evidence items. A signal is never stored without them.
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    # active | acknowledged | dismissed
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
