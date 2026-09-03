"""The escalation verdict is visible on the queue itself (Phase 42).

The point of surfacing it here is that the decision to spend money is made
by a person looking at a list, and the list should tell them which entries
are worth paying for *before* they click.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from brain.research.change_detection import ChangeType

NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.UTC)


def _entry(
    session: Session, asset: models.Asset, change_type: str, importance: float
) -> models.ResearchQueueEntry:
    entry = models.ResearchQueueEntry(
        asset_id=asset.id,
        ticker=asset.ticker,
        change_type=change_type,
        status="pending",
        score=importance,
        importance=importance,
        novelty=0.5,
        portfolio_impact=0.5,
        watchlist_relevance=0.5,
        reasons=["fixture"],
        detail={},
        detected_at=NOW,
    )
    session.add(entry)
    session.commit()
    return entry


def test_a_material_thesis_violation_is_marked_worth_escalating(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    _entry(db_session, seeded_asset, str(ChangeType.THESIS_VIOLATION), 0.9)

    entry = client.get("/research/queue").json()[0]

    assert entry["ai_recommendation"]["escalate"] is True
    assert entry["ai_recommendation"]["tier"] == "TIER_3_FRONTIER_HIGH"
    assert entry["ai_recommendation"]["reason"]


def test_a_price_move_is_marked_not_worth_escalating(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """Queued for a human to see, but explicitly not worth a model."""
    _entry(db_session, seeded_asset, str(ChangeType.PRICE_SHOCK), 1.0)

    entry = client.get("/research/queue").json()[0]

    assert entry["ai_recommendation"]["escalate"] is False
    assert entry["ai_recommendation"]["outcome"] == "deterministic_only"


def test_the_refusal_explains_itself_to_the_reader(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    _entry(db_session, seeded_asset, str(ChangeType.EARNINGS_RELEASE), 0.1)

    recommendation = client.get("/research/queue").json()[0]["ai_recommendation"]

    assert recommendation["escalate"] is False
    assert "threshold" in recommendation["reason"]


def test_an_unrecognised_change_type_yields_no_recommendation(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """No guessed verdict. A null recommendation reads as 'no policy',
    which is true; a fabricated `escalate: false` would not be."""
    _entry(db_session, seeded_asset, "something_from_the_future", 0.9)

    assert client.get("/research/queue").json()[0]["ai_recommendation"] is None


def test_processing_is_still_a_human_decision(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """The recommendation informs; it does not act. Listing the queue must
    never itself invoke a model -- that would make merely *looking* at the
    system cost money.
    """
    _entry(db_session, seeded_asset, str(ChangeType.THESIS_VIOLATION), 0.95)

    client.get("/research/queue")

    # "recorded: false" is the honest answer when nothing has run -- and it
    # is exactly what must still be true after listing the queue.
    usage = client.get("/ai/usage").json()
    assert usage["recorded"] is False
