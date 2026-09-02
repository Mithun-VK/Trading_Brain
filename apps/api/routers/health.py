"""Health and lineage endpoints.

`/health` aggregates real dependency, data and job checks. A running
process is not a healthy system, so this endpoint can and does report
degraded/unavailable while the API itself answers fine. `/health/live` is
the liveness-only probe for orchestrators.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from config.settings import get_settings
from models.signal import Signal
from models.thesis import Thesis
from models.trade import Trade
from observability.checks import (
    aggregate,
    data_checks,
    dependency_checks,
    full_health,
    job_checks,
)
from observability.lineage import (
    learning_metric_lineage,
    signal_lineage,
    thesis_lineage,
    trade_lineage,
)

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Aggregate health: healthy | degraded | unavailable.

    If the database is unreachable, the dependency raises and the
    app-level SQLAlchemy handler in `apps.api.main` converts it into a 503
    with an `unavailable` body -- /health must report an outage, never 500
    because of one.
    """
    return full_health(session)


@router.get("/health/live")
def liveness() -> dict:
    """Process liveness only. Says nothing about whether the system works."""
    return {"status": "ok", "app_env": get_settings().app_env}


@router.get("/health/dependencies")
def dependencies(session: Session = Depends(get_session)) -> dict:
    checks = dependency_checks(session)
    return {"status": str(aggregate(checks)), "checks": [c.to_dict() for c in checks]}


@router.get("/health/data")
def data(session: Session = Depends(get_session)) -> dict:
    checks = data_checks(session)
    return {"status": str(aggregate(checks)), "checks": [c.to_dict() for c in checks]}


@router.get("/health/jobs")
def jobs(session: Session = Depends(get_session)) -> dict:
    checks = job_checks(session)
    return {"status": str(aggregate(checks)), "checks": [c.to_dict() for c in checks]}


@router.get("/lineage/signals/{signal_id}")
def signal_provenance(signal_id: int, session: Session = Depends(get_session)) -> dict:
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"No signal with id {signal_id}")
    return signal_lineage(session, signal)


@router.get("/lineage/trades/{trade_id}")
def trade_provenance(trade_id: int, session: Session = Depends(get_session)) -> dict:
    trade = session.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"No trade with id {trade_id}")
    return trade_lineage(session, trade)


@router.get("/lineage/theses/{thesis_id}")
def thesis_provenance(thesis_id: int, session: Session = Depends(get_session)) -> dict:
    thesis = session.get(Thesis, thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"No thesis with id {thesis_id}")
    return thesis_lineage(session, thesis)


@router.get("/lineage/learning")
def learning_provenance(session: Session = Depends(get_session)) -> dict:
    from data.storage.learning_repository import get_learning_reviews

    reviews = get_learning_reviews(session, limit=1)
    if not reviews:
        raise HTTPException(status_code=404, detail="No learning report has been generated")
    return learning_metric_lineage(session, dict(reviews[0].metrics or {}))
