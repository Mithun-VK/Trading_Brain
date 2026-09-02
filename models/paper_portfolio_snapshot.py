from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class PaperPortfolioSnapshot(Base):
    """Point-in-time portfolio valuation.

    Exposure and allocation can be computed on demand, but **drawdown
    cannot** -- it needs an equity history. These rows are that history.
    Unique per (portfolio, as_of) so a re-run of the daily job updates
    rather than duplicating.
    """

    __tablename__ = "paper_portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "as_of", name="uq_paper_snapshots_portfolio_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True
    )
    as_of: Mapped[dt.date] = mapped_column(index=True)
    cash: Mapped[float] = mapped_column(Numeric(18, 6))
    positions_value: Mapped[float] = mapped_column(Numeric(18, 6))
    equity: Mapped[float] = mapped_column(Numeric(18, 6))
    exposure: Mapped[float] = mapped_column(Numeric(9, 6), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(18, 6), default=0)
    # How many open positions had no price available at snapshot time --
    # a valuation computed over partial data must say so.
    unpriced_positions: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
