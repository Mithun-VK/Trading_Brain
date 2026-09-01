from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FinancialMetric(Base):
    """A single fundamental data point, e.g. (RELIANCE, 'pe_ratio', 'TTM', 2026-06-30) -> 24.3."""

    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "metric_name",
            "period",
            "as_of_date",
            name="uq_financial_metrics_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    period: Mapped[str] = mapped_column(String(32))  # e.g. "FY2025Q4", "TTM"
    value: Mapped[float] = mapped_column(Numeric(24, 6))
    as_of_date: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
