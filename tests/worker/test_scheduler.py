from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus, JobTrigger
from apps.worker.scheduler.schedule import Schedule
from apps.worker.scheduler.scheduler import JobScheduler
from data.storage.job_repository import get_recent_job_runs
from models.base import Base

NOW = dt.datetime(2026, 1, 10, 22, 30, tzinfo=dt.UTC)


class _CountingJob(Job):
    name = "counting"

    def __init__(self, fail_times: int = 0, status: JobStatus = JobStatus.SUCCESS) -> None:
        self.runs = 0
        self.fail_times = fail_times
        self.status = status

    def run(self, context: JobContext) -> JobResult:
        self.runs += 1
        if self.runs <= self.fail_times:
            raise RuntimeError(f"boom {self.runs}")
        return JobResult(job_name=self.name, status=self.status, items_processed=3)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def context(session: Session) -> JobContext:
    return JobContext(session=session, now=NOW)


def test_register_and_list(context: JobContext) -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(), Schedule.daily(at=dt.time(22, 0)))

    assert scheduler.registered() == ["counting"]
    assert "daily" in scheduler.describe()["counting"]


def test_duplicate_registration_is_rejected() -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(), Schedule.manual())

    with pytest.raises(ValueError, match="already registered"):
        scheduler.register(_CountingJob(), Schedule.manual())


def test_unknown_job_raises() -> None:
    with pytest.raises(KeyError, match="Unknown job"):
        JobScheduler().get("nope")


def test_run_job_records_an_audit_row(context: JobContext) -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(), Schedule.manual())

    result = scheduler.run_job("counting", context, trigger=JobTrigger.MANUAL)

    assert result.status is JobStatus.SUCCESS
    runs = get_recent_job_runs(context.session)
    assert len(runs) == 1
    assert runs[0].job_name == "counting"
    assert runs[0].trigger == "manual"
    assert runs[0].items_processed == 3
    assert runs[0].duration_ms is not None


def test_job_exception_is_captured_not_raised(context: JobContext) -> None:
    """A failing job must not take down the worker."""
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(fail_times=99), Schedule.manual())

    result = scheduler.run_job("counting", context)

    assert result.status is JobStatus.FAILED
    assert "RuntimeError: boom" in (result.error or "")
    assert get_recent_job_runs(context.session)[0].status == "failed"


def test_retry_succeeds_on_a_later_attempt(context: JobContext) -> None:
    job = _CountingJob(fail_times=2)
    scheduler = JobScheduler()
    scheduler.register(job, Schedule.manual())

    result = scheduler.run_job("counting", context, max_attempts=3)

    assert result.status is JobStatus.SUCCESS
    assert job.runs == 3
    # Every attempt is recorded, so a flaky job is visible after the fact.
    runs = get_recent_job_runs(context.session)
    assert len(runs) == 3
    assert [r.status for r in runs] == ["success", "failed", "failed"]


def test_retry_gives_up_after_max_attempts(context: JobContext) -> None:
    job = _CountingJob(fail_times=99)
    scheduler = JobScheduler()
    scheduler.register(job, Schedule.manual())

    result = scheduler.run_job("counting", context, max_attempts=2)

    assert result.status is JobStatus.FAILED
    assert job.runs == 2


def test_due_jobs_uses_persisted_history(context: JobContext) -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(), Schedule.daily(at=dt.time(22, 0)))

    assert scheduler.due_jobs(context) == ["counting"]

    scheduler.run_job("counting", context, trigger=JobTrigger.SCHEDULED)

    # Same day -> no longer due, and that survives a fresh scheduler instance.
    assert scheduler.due_jobs(context) == []
    fresh = JobScheduler()
    fresh.register(_CountingJob(), Schedule.daily(at=dt.time(22, 0)))
    assert fresh.due_jobs(context) == []


def test_failed_run_does_not_satisfy_the_schedule(context: JobContext) -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(fail_times=99), Schedule.daily(at=dt.time(22, 0)))

    scheduler.run_job("counting", context, trigger=JobTrigger.SCHEDULED)

    assert scheduler.due_jobs(context) == ["counting"]


def test_partial_run_does_satisfy_the_schedule(context: JobContext) -> None:
    """PARTIAL means the job completed and made progress -- don't loop on it."""
    scheduler = JobScheduler()
    scheduler.register(
        _CountingJob(status=JobStatus.PARTIAL), Schedule.daily(at=dt.time(22, 0))
    )

    scheduler.run_job("counting", context, trigger=JobTrigger.SCHEDULED)

    assert scheduler.due_jobs(context) == []


def test_run_due_only_runs_due_jobs(context: JobContext) -> None:
    due_job = _CountingJob()
    manual_job = _CountingJob()
    manual_job.name = "manual_only"

    scheduler = JobScheduler()
    scheduler.register(due_job, Schedule.daily(at=dt.time(22, 0)))
    scheduler.register(manual_job, Schedule.manual())

    results = scheduler.run_due(context)

    assert [r.job_name for r in results] == ["counting"]
    assert due_job.runs == 1
    assert manual_job.runs == 0


def test_scheduled_runs_are_labelled_as_scheduled(context: JobContext) -> None:
    scheduler = JobScheduler()
    scheduler.register(_CountingJob(), Schedule.daily(at=dt.time(22, 0)))

    scheduler.run_due(context)

    assert get_recent_job_runs(context.session)[0].trigger == "scheduled"


# -- resilience of the runner itself (Phase 31) -------------------------------


class _DatabaseErrorJob(Job):
    """Fails the way a writing job fails: a flush the database rejects.

    A failed SELECT leaves the session usable; a failed flush does not. Every
    ingestion job writes, so this is the realistic failure mode.
    """

    name = "db_error"

    def run(self, context: JobContext) -> JobResult:
        from models.job_run import JobRun

        try:
            context.session.add(JobRun(job_name=None, status="x", trigger="m"))
            context.session.flush()
        except Exception as exc:
            raise RuntimeError("job hit a database error") from exc
        return JobResult(job_name=self.name, status=JobStatus.SUCCESS)


def test_a_database_error_inside_a_job_still_records_the_failure(
    context: JobContext,
) -> None:
    """The scheduler is what records failures, so it has to survive the
    failure it is recording.

    A job that dies on a rejected flush leaves the session in a failed
    transaction. Writing the job_run row without rolling back first raises
    PendingRollbackError from *outside* the try block -- killing the worker
    and losing the record, at exactly the moment the record matters most.
    """
    scheduler = JobScheduler()
    scheduler.register(_DatabaseErrorJob(), Schedule.daily(at=dt.time(22, 0)))

    result = scheduler.run_job("db_error", context)

    assert result.status is JobStatus.FAILED
    runs = get_recent_job_runs(context.session, limit=10)
    assert len(runs) == 1
    assert "database error" in (runs[0].error or "")
