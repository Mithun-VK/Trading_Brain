from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from models.company import Company


class Asset(Base, TimestampMixin):
    """A tradeable instrument. Companies, ETFs, indices, and crypto all get
    an Asset row; `Company` adds equity-specific fields for asset_type='equity'.
    """

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("ticker", "exchange", name="uq_assets_ticker_exchange"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(32))
    asset_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    company: Mapped[Company | None] = relationship(
        "Company", back_populates="asset", uselist=False
    )
