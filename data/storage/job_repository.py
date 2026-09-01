"""Persistence for job runs -- both the audit trail and the scheduler's
durable memory of when each job last succeeded.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.job_run import JobRun


def record_job_run(
    session: Session,
    job_name: str,
    status: str,
    trigger: str,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    attempt: int = 1,
    items_processed: int = 0,
    detail: dict | None = None,
    error: str | None = None,
) -> JobRun:
    row = JobRun(
        job_name=job_name,
        status=status,
        trigger=trigger,
        attempt=attempt,
        items_processed=items_processed,
        detail=detail or {},
        error=error,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=round((finished_at - started_at).total_seconds() * 1000, 2),
    )
    session.add(row)
    session.flush()
    return row


def get_last_successful_run(session: Session, job_name: str) -> JobRun | None:
    """Last run the scheduler should count as "done" -- PARTIAL counts, since
    the job completed and made progress; FAILED does not.
    """
    return session.scalars(
        select(JobRun)
        .where(JobRun.job_name == job_name, JobRun.status.in_(("success", "partial")))
        .order_by(JobRun.started_at.desc())
    ).first()


def get_recent_job_runs(
    session: Session, job_name: str | None = None, limit: int = 50
) -> list[JobRun]:
    query = select(JobRun).order_by(JobRun.started_at.desc())
    if job_name:
        query = query.where(JobRun.job_name == job_name)
    return list(session.scalars(query.limit(limit)).all())
