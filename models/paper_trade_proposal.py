"""Paper trade proposals.

A proposal is a *suggestion awaiting a human decision*. It becomes a
simulated transaction only after explicit approval -- `execute_proposal`
refuses any other status, so an approval step cannot be skipped by
accident (Rule 7: Claude does not execute trades; the human decides).

Even after approval, execution writes rows in this database and nothing
else. No broker connectivity exists (Rule 8).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.asset import Asset

STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXECUTED = "executed"
STATUS_EXPIRED = "expired"


class PaperTradeProposal(Base, TimestampMixin):
    __tablename__ = "paper_trade_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)

    side: Mapped[str] = mapped_column(String(8))  # buy | sell (simulated only)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6))
    reference_price: Mapped[float] = mapped_column(Numeric(18, 6))
    stop_price: Mapped[float | None] = mapped_column(Numeric(18, 6))

    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    rationale: Mapped[str] = mapped_column(Text)
    # The signal that prompted this, so a proposal is traceable to evidence.
    source_signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), index=True)

    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    executed_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_transactions.id")
    )

    asset: Mapped[Asset] = relationship("Asset")
