"""Research queue persistence.

Enqueueing is **idempotent by (asset, change_type) while an entry is still
pending**: a repeat detection refreshes the existing row's score instead of
piling up duplicates. That keeps a daily detection job safe to re-run.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.research.change_detection import DetectedChange
from brain.research.priority import ResearchPriority
from models.research_queue import ResearchQueueEntry

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"

_OPEN_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)


def enqueue(
    session: Session,
    priority: ResearchPriority,
    change: DetectedChange,
    now: dt.datetime | None = None,
) -> tuple[ResearchQueueEntry, bool]:
    """Add or refresh a queue entry. Returns (entry, created)."""
    now = now or dt.datetime.now(dt.UTC)
    existing = session.scalars(
        select(ResearchQueueEntry).where(
            ResearchQueueEntry.asset_id == priority.asset_id,
            ResearchQueueEntry.change_type == str(priority.change_type),
            ResearchQueueEntry.status.in_(_OPEN_STATUSES),
        )
    ).first()

    if existing is not None:
        existing.score = priority.score
        existing.importance = priority.importance
        existing.novelty = priority.novelty
        existing.portfolio_impact = priority.portfolio_impact
        existing.watchlist_relevance = priority.watchlist_relevance
        existing.reasons = priority.reasons
        existing.detail = change.detail
        existing.detected_at = change.detected_at
        session.flush()
        return existing, False

    entry = ResearchQueueEntry(
        asset_id=priority.asset_id,
        ticker=priority.ticker,
        change_type=str(priority.change_type),
        status=STATUS_PENDING,
        score=priority.score,
        importance=priority.importance,
        novelty=priority.novelty,
        portfolio_impact=priority.portfolio_impact,
        watchlist_relevance=priority.watchlist_relevance,
        reasons=priority.reasons,
        detail=change.detail,
        detected_at=change.detected_at,
    )
    session.add(entry)
    session.flush()
    return entry, True


def get_queue(
    session: Session, status: str = STATUS_PENDING, limit: int | None = None
) -> list[ResearchQueueEntry]:
    """Highest-priority first -- the order the queue should be worked in."""
    query = (
        select(ResearchQueueEntry)
        .where(ResearchQueueEntry.status == status)
        .order_by(ResearchQueueEntry.score.desc(), ResearchQueueEntry.detected_at.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query).all())


def next_entry(session: Session) -> ResearchQueueEntry | None:
    entries = get_queue(session, limit=1)
    return entries[0] if entries else None


def mark_in_progress(
    session: Session, entry: ResearchQueueEntry, now: dt.datetime | None = None
) -> ResearchQueueEntry:
    entry.status = STATUS_IN_PROGRESS
    session.flush()
    return entry


def mark_done(
    session: Session,
    entry: ResearchQueueEntry,
    research_document_id: int | None = None,
    now: dt.datetime | None = None,
) -> ResearchQueueEntry:
    entry.status = STATUS_DONE
    entry.processed_at = now or dt.datetime.now(dt.UTC)
    entry.research_document_id = research_document_id
    session.flush()
    return entry


def dismiss(
    session: Session,
    entry: ResearchQueueEntry,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> ResearchQueueEntry:
    """Close an entry without researching it. The note is kept so a
    dismissal is auditable rather than silent.
    """
    entry.status = STATUS_DISMISSED
    entry.processed_at = now or dt.datetime.now(dt.UTC)
    if note:
        entry.note = note
    session.flush()
    return entry
