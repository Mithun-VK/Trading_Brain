from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.asset import Asset


class Watchlist(Base, TimestampMixin):
    """A named set of assets: a theme, a sector, or a personal list.

    Watchlists drive what the ingestion and research engines prioritize, so
    they're first-class rows rather than browser-local state.
    """

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # theme | sector | personal
    kind: Mapped[str] = mapped_column(String(32), default="personal", index=True)

    items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem",
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "asset_id", name="uq_watchlist_items_list_asset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    watchlist: Mapped[Watchlist] = relationship("Watchlist", back_populates="items")
    asset: Mapped[Asset] = relationship("Asset")
