from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class JobRun(Base):
    """Audit record for one execution of a scheduled/manual worker job.

    This table is also the scheduler's memory: "when did this job last
    succeed?" is answered from here rather than from in-process state, so
    schedules survive worker restarts and are correct across replicas.
    """

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # success|failed|partial|skipped
    trigger: Mapped[str] = mapped_column(String(16))  # scheduled|manual
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
