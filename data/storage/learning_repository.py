from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.learning_review import LearningReview
from models.thesis_review_record import ThesisReviewRecord

if TYPE_CHECKING:
    # Type-only: importing brain.learning at runtime would cycle back here
    # via its package __init__ -> engine -> this module.
    from brain.learning.schemas import LearningReport


def save_learning_review(
    session: Session, report: LearningReport, note_path: str | None = None
) -> LearningReview:
    """Upsert by (kind, period_start): regenerating a period's review
    refreshes it rather than accumulating near-duplicate rows.
    """
    review = session.scalars(
        select(LearningReview).where(
            LearningReview.kind == str(report.kind),
            LearningReview.period_start == report.period_start,
        )
    ).first()
    if review is None:
        review = LearningReview(
            kind=str(report.kind), period_start=report.period_start
        )
        session.add(review)

    review.period_end = report.period_end
    review.metrics = report.to_dict()
    review.generated_at = report.generated_at
    review.obsidian_note_path = note_path
    session.flush()
    return review


def get_learning_reviews(
    session: Session, kind: str | None = None, limit: int | None = None
) -> list[LearningReview]:
    query = select(LearningReview).order_by(LearningReview.period_start.desc())
    if kind:
        query = query.where(LearningReview.kind == kind)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query).all())


def record_thesis_review(
    session: Session,
    thesis_id: int,
    asset_id: int | None,
    previous_assessment: str,
    assessment: str,
    reviewed_at: dt.datetime,
    confidence: float | None = None,
    reasoning: str | None = None,
) -> ThesisReviewRecord:
    """Persist one thesis assessment transition in queryable form.

    The Obsidian note remains the narrative audit trail; this makes the
    same history measurable by the learning loop.
    """
    record = ThesisReviewRecord(
        thesis_id=thesis_id,
        asset_id=asset_id,
        previous_assessment=previous_assessment,
        assessment=assessment,
        confidence=confidence,
        reasoning=reasoning,
        reviewed_at=reviewed_at,
    )
    session.add(record)
    session.flush()
    return record
