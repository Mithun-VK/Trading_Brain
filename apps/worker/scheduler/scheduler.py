"""Job scheduler: registration, due-detection, retry, and run recording.

The scheduler owns *when* and *how many times*; jobs own *what*. Every run
is written to `job_runs`, which doubles as the durable answer to "when did
this last succeed?" -- so restarting the worker never re-runs a completed
daily job, and never skips a missed one.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus, JobTrigger
from apps.worker.scheduler.schedule import Schedule
from config.logging import get_logger
from data.storage.job_repository import get_last_successful_run, record_job_run

logger = get_logger("worker")


@dataclass(frozen=True)
class RegisteredJob:
    job: Job
    schedule: Schedule


class JobScheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, RegisteredJob] = {}

    # -- registration ---------------------------------------------------------

    def register(self, job: Job, schedule: Schedule) -> None:
        if job.name in self._jobs:
            raise ValueError(f"Job {job.name!r} is already registered")
        self._jobs[job.name] = RegisteredJob(job=job, schedule=schedule)

    def registered(self) -> list[str]:
        return sorted(self._jobs)

    def get(self, name: str) -> RegisteredJob:
        registration = self._jobs.get(name)
        if registration is None:
            known = ", ".join(self.registered()) or "none"
            raise KeyError(f"Unknown job {name!r} (registered: {known})")
        return registration

    def describe(self) -> dict[str, str]:
        return {name: reg.schedule.describe() for name, reg in self._jobs.items()}

    # -- scheduling -----------------------------------------------------------

    def due_jobs(self, context: JobContext) -> list[str]:
        due = []
        for name, registration in sorted(self._jobs.items()):
            last = get_last_successful_run(context.session, name)
            if registration.schedule.is_due(context.now, last.started_at if last else None):
                due.append(name)
        return due

    def run_due(self, context: JobContext, max_attempts: int = 1) -> list[JobResult]:
        return [
            self.run_job(name, context, trigger=JobTrigger.SCHEDULED, max_attempts=max_attempts)
            for name in self.due_jobs(context)
        ]

    # -- execution ------------------------------------------------------------

    def run_job(
        self,
        name: str,
        context: JobContext,
        trigger: JobTrigger = JobTrigger.MANUAL,
        max_attempts: int = 1,
        retry_delay_seconds: float = 0.0,
    ) -> JobResult:
        """Run one job, retrying on unhandled exceptions. Every attempt is
        recorded, so a job that succeeds on attempt 3 leaves a full trail.
        """
        registration = self.get(name)
        last_result: JobResult | None = None

        for attempt in range(1, max_attempts + 1):
            started_at = dt.datetime.now(dt.UTC)
            try:
                result = registration.job.run(context)
            except Exception as exc:  # noqa: BLE001 -- a job must never kill the worker
                result = JobResult(
                    job_name=name,
                    status=JobStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                )
                logger.warning(
                    "job_failed",
                    operation=name,
                    status="error",
                    attempt=attempt,
                    error=type(exc).__name__,
                )
            else:
                logger.info(
                    "job_completed",
                    operation=name,
                    status=str(result.status),
                    attempt=attempt,
                    items=result.items_processed,
                )

            finished_at = dt.datetime.now(dt.UTC)
            record_job_run(
                context.session,
                job_name=name,
                status=str(result.status),
                trigger=str(trigger),
                started_at=started_at,
                finished_at=finished_at,
                attempt=attempt,
                items_processed=result.items_processed,
                detail=result.detail,
                error=result.error,
            )
            context.session.commit()

            last_result = result
            if result.status is not JobStatus.FAILED:
                return result
            if attempt < max_attempts and retry_delay_seconds:
                time.sleep(retry_delay_seconds)

        assert last_result is not None  # loop always runs at least once
        return last_result
