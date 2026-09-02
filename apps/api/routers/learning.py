"""Learning reports API.

Returns the stored report metrics **verbatim**. The learning engine already
encodes the honesty rules -- sample sizes, significance flags, caveats,
non-directional signals excluded from scoring, and research explicitly
marked `is_accuracy_score: false`. This router must not summarise those
away, so it passes the metrics dict through untouched rather than
cherry-picking headline numbers (Rules 11/12).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies import get_knowledge_store, get_session
from apps.api.schemas_v2 import LearningGenerateIn, LearningReportOut
from brain.learning.engine import LearningEngine
from brain.learning.schemas import ReviewKind
from data.storage.learning_repository import get_learning_reviews
from integrations.obsidian.errors import ObsidianError
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.learning_review import LearningReview

router = APIRouter(tags=["learning"])


def _to_out(review: LearningReview) -> LearningReportOut:
    return LearningReportOut(
        id=review.id,
        kind=review.kind,
        period_start=review.period_start,
        period_end=review.period_end,
        generated_at=review.generated_at,
        obsidian_note_path=review.obsidian_note_path,
        metrics=dict(review.metrics or {}),
    )


@router.get("/learning/reports", response_model=list[LearningReportOut])
def list_reports(
    kind: str | None = None,
    limit: int = Query(default=24, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[LearningReportOut]:
    return [_to_out(r) for r in get_learning_reviews(session, kind=kind, limit=limit)]


@router.get("/learning/reports/{report_id}", response_model=LearningReportOut)
def get_report(report_id: int, session: Session = Depends(get_session)) -> LearningReportOut:
    review = session.get(LearningReview, report_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"No learning report with id {report_id}")
    return _to_out(review)


@router.post("/learning/reports/generate", response_model=LearningReportOut, status_code=201)
def generate_report(
    payload: LearningGenerateIn,
    session: Session = Depends(get_session),
) -> LearningReportOut:
    """Generate (or refresh) a period's review.

    Obsidian publication is opt-in: the PostgreSQL record is always written,
    and an unreachable vault never loses the report.
    """
    kind = ReviewKind(payload.kind)
    engine = LearningEngine()
    report = engine.build_report(session, kind=kind, as_of=payload.as_of)

    knowledge_store: KnowledgeStore | None = None
    if payload.publish_to_obsidian:
        try:
            generator = get_knowledge_store()
            knowledge_store = next(generator)
        except (ObsidianError, HTTPException, StopIteration):
            knowledge_store = None

    try:
        engine.publish(session, report, knowledge_store=knowledge_store)
    except ObsidianError:
        # The vault write failed; keep the PostgreSQL record rather than
        # losing the whole review.
        engine.publish(session, report, knowledge_store=None)
    session.commit()

    reviews = get_learning_reviews(session, kind=str(kind), limit=1)
    if not reviews:  # pragma: no cover -- publish always writes a row
        raise HTTPException(status_code=500, detail="Report was generated but not stored")
    return _to_out(reviews[0])


@router.get("/learning/summary")
def learning_summary(session: Session = Depends(get_session)) -> dict:
    """Latest report's headline figures, each paired with its caveat.

    Deliberately returns `null` (not 0.0) where nothing has resolved, so a
    dashboard can distinguish "unknown" from "zero".
    """
    reviews = get_learning_reviews(session, limit=1)
    if not reviews:
        return {
            "available": False,
            "reason": "No learning review has been generated yet.",
        }

    metrics = dict(reviews[0].metrics or {})
    signal_block = metrics.get("signal_accuracy", {}).get("overall", {})
    thesis_block = metrics.get("thesis_accuracy", {})
    research_block = metrics.get("research_outcomes", {})

    return {
        "available": True,
        "period_start": reviews[0].period_start.isoformat(),
        "period_end": reviews[0].period_end.isoformat(),
        "generated_at": reviews[0].generated_at.isoformat(),
        "signal_accuracy": signal_block.get("accuracy"),
        "signal_sample_size": signal_block.get("sample_size"),
        "signal_is_significant": signal_block.get("is_significant"),
        "signal_caveat": signal_block.get("caveat"),
        "theses_tracked": thesis_block.get("total_theses"),
        "invalidation_rate": thesis_block.get("invalidation_rate"),
        "median_days_to_invalidation": thesis_block.get("median_days_to_invalidation"),
        "research_is_accuracy_score": research_block.get("is_accuracy_score", False),
        "research_note": research_block.get("why_not_accuracy"),
    }


@router.get("/learning/kinds")
def review_kinds() -> dict[str, list[str]]:
    return {"kinds": [str(k) for k in ReviewKind]}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
