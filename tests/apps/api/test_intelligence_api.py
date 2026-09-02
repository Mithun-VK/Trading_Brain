from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models

GENERATED_AT = dt.datetime(2026, 3, 1, 12, 0, tzinfo=dt.UTC)


def _signal(
    db_session: Session,
    asset: models.Asset,
    category: str = "ACCUMULATE",
    confidence: float = 0.8,
    status: str = "active",
    evidence: list | None = None,
    when: dt.datetime = GENERATED_AT,
) -> models.Signal:
    signal = models.Signal(
        asset_id=asset.id,
        signal_type="rule",
        category=category,
        confidence=confidence,
        reasoning=f"{category} reasoning",
        evidence=evidence
        if evidence is not None
        else [{"kind": "quant", "detail": "momentum positive", "stance": "supports"}],
        value={},
        source="brain.signals.engine",
        status=status,
        generated_at=when,
    )
    db_session.add(signal)
    db_session.commit()
    return signal


def _queue_entry(
    db_session: Session, asset: models.Asset, score: float = 0.8, status: str = "pending"
) -> models.ResearchQueueEntry:
    entry = models.ResearchQueueEntry(
        asset_id=asset.id,
        ticker=asset.ticker,
        change_type="price_shock",
        status=status,
        score=score,
        importance=0.9,
        novelty=0.5,
        portfolio_impact=0.2,
        watchlist_relevance=0.6,
        reasons=["price_shock on RELIANCE"],
        detail={"return": 0.08},
        detected_at=GENERATED_AT,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


# -- signals ------------------------------------------------------------------


def test_signals_empty(client: TestClient) -> None:
    assert client.get("/signals").json() == []


def test_signal_includes_evidence_and_lineage(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    db_session.add(
        models.MarketRegimeObservation(
            observed_at=GENERATED_AT - dt.timedelta(days=1),
            regime="BULLISH",
            volatility_regime="LOW_VOLATILITY",
            risk_regime="RISK_ON",
        )
    )
    db_session.add(
        models.Thesis(
            asset_id=seeded_asset.id, title="t", status="active",
            current_assessment="THESIS_INTACT",
        )
    )
    db_session.commit()
    _signal(db_session, seeded_asset)

    body = client.get("/signals").json()

    assert len(body) == 1
    assert body[0]["evidence"]
    assert body[0]["market_regime"] == "BULLISH"
    assert body[0]["thesis_assessment"] == "THESIS_INTACT"
    assert body[0]["reasoning"]


def test_a_signal_without_evidence_is_never_served(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """Rule 10: no bare recommendation without traceability."""
    _signal(db_session, seeded_asset, evidence=[])

    assert client.get("/signals").json() == []


def test_getting_an_evidence_free_signal_by_id_errors(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    signal = _signal(db_session, seeded_asset, evidence=[])

    response = client.get(f"/signals/{signal.id}")

    assert response.status_code == 500
    assert "Rule 10" in response.json()["detail"]


def test_signal_filters(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    _signal(db_session, seeded_asset, category="ACCUMULATE", confidence=0.9)
    _signal(db_session, seeded_asset, category="WATCH", confidence=0.3)

    assert len(client.get("/signals", params={"category": "WATCH"}).json()) == 1
    assert len(client.get("/signals", params={"min_confidence": 0.5}).json()) == 1
    assert len(client.get("/signals", params={"ticker": "RELIANCE"}).json()) == 2
    assert len(client.get("/signals", params={"status": "acknowledged"}).json()) == 0


def test_signal_regime_filter_uses_the_regime_at_signal_time(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    db_session.add(
        models.MarketRegimeObservation(
            observed_at=GENERATED_AT - dt.timedelta(days=1),
            regime="BEARISH", volatility_regime="HIGH_VOLATILITY", risk_regime="RISK_OFF",
        )
    )
    db_session.commit()
    _signal(db_session, seeded_asset)

    assert len(client.get("/signals", params={"market_regime": "BEARISH"}).json()) == 1
    assert len(client.get("/signals", params={"market_regime": "BULLISH"}).json()) == 0


def test_unknown_ticker_filter_is_404(client: TestClient) -> None:
    assert client.get("/signals", params={"ticker": "NOPE"}).status_code == 404


def test_latest_signals_only_returns_active(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    _signal(db_session, seeded_asset, status="active")
    _signal(db_session, seeded_asset, status="acknowledged")

    body = client.get("/signals/latest").json()

    assert len(body) == 1
    assert body[0]["status"] == "active"


def test_get_signal_by_id(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    signal = _signal(db_session, seeded_asset)

    body = client.get(f"/signals/{signal.id}").json()

    assert body["id"] == signal.id
    assert body["ticker"] == "RELIANCE"


def test_unknown_signal_id_is_404(client: TestClient) -> None:
    assert client.get("/signals/999999").status_code == 404


# -- research queue -----------------------------------------------------------


def test_queue_is_ordered_by_priority(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    _queue_entry(db_session, seeded_asset, score=0.4)
    _queue_entry(db_session, seeded_asset, score=0.9)

    body = client.get("/research/queue").json()

    assert [e["score"] for e in body] == [0.9, 0.4]


def test_queue_entry_exposes_its_priority_breakdown(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    entry = _queue_entry(db_session, seeded_asset)

    body = client.get(f"/research/queue/{entry.id}").json()

    assert body["change_type"] == "price_shock"
    assert body["importance"] == 0.9
    assert body["reasons"]
    assert body["detail"]["return"] == 0.08


def test_unknown_queue_entry_is_404(client: TestClient) -> None:
    assert client.get("/research/queue/999999").status_code == 404


def test_dismiss_records_the_note(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    entry = _queue_entry(db_session, seeded_asset)

    response = client.post(
        f"/research/queue/{entry.id}/dismiss", json={"note": "known rebalance"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    assert response.json()["note"] == "known rebalance"


def test_dismissing_twice_conflicts(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    entry = _queue_entry(db_session, seeded_asset)
    client.post(f"/research/queue/{entry.id}/dismiss", json={})

    assert client.post(f"/research/queue/{entry.id}/dismiss", json={}).status_code == 409


def test_process_runs_research_and_closes_the_entry(
    client: TestClient, db_session: Session, seeded_asset: models.Asset, knowledge_store
) -> None:
    entry = _queue_entry(db_session, seeded_asset)

    response = client.post(f"/research/queue/{entry.id}/process")

    assert response.status_code == 200
    assert response.json()["ticker"] == "RELIANCE"
    assert any(p.startswith("08 Research/") for p in knowledge_store.notes)

    db_session.expire_all()
    refreshed = db_session.get(models.ResearchQueueEntry, entry.id)
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.research_document_id is not None


def test_processing_a_closed_entry_conflicts(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    entry = _queue_entry(db_session, seeded_asset, status="done")

    assert client.post(f"/research/queue/{entry.id}/process").status_code == 409
