"""Signals API.

Two invariants enforced at the transport boundary:

1. **A signal is never returned without its evidence.** A stored row with
   empty evidence is a data-integrity fault, not something to render as a
   bare recommendation -- it is skipped and logged (Rule 10).
2. Only the six attention categories exist. There is no endpoint, filter,
   or field here that could express an execution instruction (Rules 7/8).

Each signal is enriched with the lineage a reader needs to judge it: the
regime that was in force, the thesis state, and when research last ran.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_session
from apps.api.schemas_v2 import EvidenceOut, SignalOut
from config.logging import get_logger
from data.storage.price_repository import normalize_ts
from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.research_document import ResearchDocument
from models.signal import Signal
from models.thesis import Thesis

logger = get_logger("api")

router = APIRouter(tags=["signals"])


def _regime_at(session: Session, when: dt.datetime) -> str | None:
    """The regime observation in force when the signal fired -- not today's."""
    anchor = normalize_ts(when)
    observations = session.scalars(
        select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
    ).all()
    for observation in observations:
        if normalize_ts(observation.observed_at) <= anchor:
            return observation.regime
    return None


def _to_out(session: Session, signal: Signal) -> SignalOut | None:
    evidence = signal.evidence or []
    if not evidence:
        logger.warning(
            "signal_missing_evidence",
            operation="get_signals",
            status="skipped",
            signal_id=signal.id,
        )
        return None

    asset = session.get(Asset, signal.asset_id)
    thesis = session.scalars(
        select(Thesis).where(Thesis.asset_id == signal.asset_id, Thesis.status == "active")
    ).first()
    research = session.scalars(
        select(ResearchDocument)
        .where(ResearchDocument.asset_id == signal.asset_id)
        .order_by(ResearchDocument.created_at.desc())
    ).first()

    return SignalOut(
        id=signal.id,
        asset_id=signal.asset_id,
        ticker=asset.ticker if asset else "",
        category=signal.category or "",
        confidence=float(signal.confidence) if signal.confidence is not None else None,
        reasoning=signal.reasoning,
        evidence=[
            EvidenceOut(
                kind=str(item.get("kind", "")),
                detail=str(item.get("detail", "")),
                stance=str(item.get("stance", "supports")),
                value=item.get("value"),
            )
            for item in evidence
        ],
        status=signal.status,
        generated_at=signal.generated_at,
        acknowledged_at=signal.acknowledged_at,
        market_regime=_regime_at(session, signal.generated_at),
        thesis_assessment=thesis.current_assessment if thesis else None,
        latest_research_at=research.created_at if research else None,
    )


@router.get("/signals", response_model=list[SignalOut])
def list_signals(
    ticker: str | None = None,
    category: str | None = None,
    status: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    market_regime: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[SignalOut]:
    query = (
        select(Signal)
        .where(Signal.category.is_not(None))
        .order_by(Signal.generated_at.desc(), Signal.confidence.desc())
    )

    if ticker:
        asset = session.scalars(select(Asset).where(Asset.ticker == ticker)).first()
        if asset is None:
            raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker!r}")
        query = query.where(Signal.asset_id == asset.id)
    if category:
        query = query.where(Signal.category == category)
    if status:
        query = query.where(Signal.status == status)
    if min_confidence is not None:
        query = query.where(Signal.confidence >= min_confidence)
    if since is not None:
        query = query.where(Signal.generated_at >= since)
    if until is not None:
        query = query.where(Signal.generated_at <= until)

    rows = session.scalars(query.limit(limit)).all()
    results = [out for row in rows if (out := _to_out(session, row)) is not None]

    if market_regime:
        # Filtered after enrichment: the regime is derived, not a column.
        results = [r for r in results if r.market_regime == market_regime]
    return results


@router.get("/signals/latest", response_model=list[SignalOut])
def latest_signals(
    limit: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[SignalOut]:
    """Most recent active signals, highest confidence first."""
    rows = session.scalars(
        select(Signal)
        .where(Signal.category.is_not(None), Signal.status == "active")
        .order_by(Signal.generated_at.desc(), Signal.confidence.desc())
        .limit(limit)
    ).all()
    return [out for row in rows if (out := _to_out(session, row)) is not None]


@router.get("/signals/{signal_id}", response_model=SignalOut)
def get_signal(signal_id: int, session: Session = Depends(get_session)) -> SignalOut:
    signal = session.get(Signal, signal_id)
    if signal is None or signal.category is None:
        raise HTTPException(status_code=404, detail=f"No signal with id {signal_id}")

    out = _to_out(session, signal)
    if out is None:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Signal {signal_id} has no stored evidence and cannot be served. "
                "Every signal must be traceable to what produced it (Rule 10)."
            ),
        )
    return out
