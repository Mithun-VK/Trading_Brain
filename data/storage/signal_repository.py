"""Signal persistence.

Evidence and reasoning are stored alongside every signal, so a signal read
back out of the database is as auditable as the one that was generated
(Rule 10). A signal is never written without them.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.signals.schemas import GeneratedSignal, SignalError
from models.signal import Signal

STATUS_ACTIVE = "active"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_DISMISSED = "dismissed"

SOURCE = "brain.signals.engine"


def save_signal(
    session: Session, signal: GeneratedSignal, now: dt.datetime | None = None
) -> Signal:
    if not signal.evidence:
        raise SignalError("Refusing to store a signal with no evidence")

    row = Signal(
        asset_id=signal.asset_id,
        signal_type=signal.rule,
        category=str(signal.category),
        confidence=signal.confidence,
        reasoning=signal.reasoning,
        evidence=signal.evidence_payload(),
        value={"ticker": signal.ticker, "rule": signal.rule},
        source=SOURCE,
        status=STATUS_ACTIVE,
        generated_at=now or dt.datetime.now(dt.UTC),
    )
    session.add(row)
    session.flush()
    return row


def get_active_signals(
    session: Session,
    category: str | None = None,
    asset_id: int | None = None,
    limit: int | None = None,
) -> list[Signal]:
    query = (
        select(Signal)
        .where(Signal.status == STATUS_ACTIVE, Signal.category.is_not(None))
        .order_by(Signal.confidence.desc(), Signal.generated_at.desc())
    )
    if category:
        query = query.where(Signal.category == category)
    if asset_id is not None:
        query = query.where(Signal.asset_id == asset_id)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query).all())


def acknowledge(
    session: Session, signal: Signal, now: dt.datetime | None = None
) -> Signal:
    """Mark that a human has seen and accepted the signal."""
    signal.status = STATUS_ACKNOWLEDGED
    signal.acknowledged_at = now or dt.datetime.now(dt.UTC)
    session.flush()
    return signal


def dismiss(session: Session, signal: Signal, now: dt.datetime | None = None) -> Signal:
    signal.status = STATUS_DISMISSED
    signal.acknowledged_at = now or dt.datetime.now(dt.UTC)
    session.flush()
    return signal
