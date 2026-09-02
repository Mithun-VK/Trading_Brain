"""Paper portfolio tables.

**No broker connectivity exists anywhere in this system.** These rows record
simulated positions only; nothing here places, routes, or settles a real
order (Rule 8).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.asset import Asset


class PaperPortfolio(Base, TimestampMixin):
    __tablename__ = "paper_portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    base_currency: Mapped[str] = mapped_column(String(8), default="INR")
    initial_cash: Mapped[float] = mapped_column(Numeric(18, 6))
    cash_balance: Mapped[float] = mapped_column(Numeric(18, 6))
    description: Mapped[str | None] = mapped_column(Text)

    positions: Mapped[list[PaperPosition]] = relationship(
        "PaperPosition",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )


class PaperPosition(Base, TimestampMixin):
    """One row per (portfolio, asset). A closed position keeps the row with
    quantity 0 so its cumulative realized P&L survives a re-entry.
    """

    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "asset_id", name="uq_paper_positions_portfolio_asset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    average_cost: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    portfolio: Mapped[PaperPortfolio] = relationship("PaperPortfolio", back_populates="positions")
    asset: Mapped[Asset] = relationship("Asset")


class PaperTransaction(Base):
    """Immutable ledger entry. Corrections are new rows, never edits --
    the position state must always be reproducible by replaying these.
    """

    __tablename__ = "paper_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    quantity: Mapped[float] = mapped_column(Numeric(18, 6))
    price: Mapped[float] = mapped_column(Numeric(18, 6))
    fees: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    cash_delta: Mapped[float] = mapped_column(Numeric(18, 6))
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
