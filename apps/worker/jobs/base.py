"""Job contract shared by every worker job.

Every job must be **idempotent**: running it twice over the same window
produces the same end state, never duplicated rows. That property comes
from the repositories the jobs use (upsert-by-natural-key), not from
scheduler bookkeeping -- so a manual re-run is always safe.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from data.ingestion.registry import ProviderRegistry
from integrations.obsidian.knowledge_store import KnowledgeStore


class JobStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"  # completed, but some items failed
    FAILED = "failed"
    SKIPPED = "skipped"


class JobTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass
class JobContext:
    """Everything a job is allowed to touch. Passing `now` explicitly (rather
    than calling the clock inside a job) keeps job behaviour deterministic
    and testable.
    """

    session: Session
    now: dt.datetime
    registry: ProviderRegistry | None = None
    knowledge_store: KnowledgeStore | None = None


@dataclass
class JobResult:
    job_name: str
    status: JobStatus
    items_processed: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (JobStatus.SUCCESS, JobStatus.PARTIAL, JobStatus.SKIPPED)


class Job(ABC):
    """A unit of scheduled work."""

    name: str

    @abstractmethod
    def run(self, context: JobContext) -> JobResult:
        """Execute the job. Should raise only on unrecoverable failure --
        per-item problems belong in JobResult.detail with PARTIAL status.
        """
