from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class BacktestRun(Base):
    """A completed backtest, stored so results are auditable and comparable.

    The full parameter set is persisted alongside the metrics: a metric
    without the configuration that produced it isn't reproducible, and
    reproducibility is the point of this engine.
    """

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    period_start: Mapped[dt.date] = mapped_column(Date)
    period_end: Mapped[dt.date] = mapped_column(Date)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    commission_bps: Mapped[float] = mapped_column(Numeric(9, 4), default=0)
    slippage_bps: Mapped[float] = mapped_column(Numeric(9, 4), default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSON, default=list)
    closed_trades: Mapped[list] = mapped_column(JSON, default=list)
    unfilled: Mapped[list] = mapped_column(JSON, default=list)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
