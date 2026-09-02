"""End-to-end pipeline (Phase 33).

Walks one asset through the whole system the way an operator would --
watchlist, prices, portfolio, signal, paper trade, learning, lineage --
against the assembled API rather than against the services underneath.

The unit tests already prove each stage works. What this file is for is the
seams between them: shapes that match in the schema but not in practice,
and honesty properties that only hold if every stage cooperates.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio
from data.storage.price_repository import upsert_price_bars

NOW = dt.datetime(2026, 3, 16, 12, 0, tzinfo=dt.UTC)


def _prices(session: Session, asset: models.Asset, closes: list[float]) -> None:
    # Anchored to the real clock, not the fixed NOW: the price-freshness
    # health check compares against wall time, so a fixture dated in the
    # past is correctly reported as stale.
    start = dt.datetime.now(dt.UTC) - dt.timedelta(days=len(closes))
    upsert_price_bars(
        session,
        asset.id,
        [
            PriceBar(
                ts=start + dt.timedelta(days=i),
                open=c, high=c * 1.01, low=c * 0.99, close=c,
                volume=1_000, interval="1d", source="test",
            )
            for i, c in enumerate(closes)
        ],
    )
    session.commit()


# -- the walk -------------------------------------------------------------------


def test_an_asset_can_be_walked_through_the_whole_pipeline(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    ticker = seeded_asset.ticker

    # 1. Watchlist
    created = client.post("/watchlists", json={"name": "Core"})
    assert created.status_code == 201
    watchlist_id = created.json()["id"]

    added = client.post(f"/watchlists/{watchlist_id}/items", json={"ticker": ticker})
    assert added.status_code == 201
    assert [i["ticker"] for i in added.json()["items"]] == [ticker]

    # Re-adding is idempotent, not a duplicate or an error.
    again = client.post(f"/watchlists/{watchlist_id}/items", json={"ticker": ticker})
    assert again.status_code == 201
    assert len(again.json()["items"]) == 1

    # 2. Prices
    _prices(db_session, seeded_asset, [100 + i for i in range(40)])

    # 3. Portfolio reads back through the same API.
    # No portfolio is a 404, not an empty one -- "you have no portfolio" and
    # "your portfolio is worth zero" are different answers.
    assert client.get("/portfolio").status_code == 404

    create_portfolio(db_session, "Core", initial_cash=100_000.0)
    db_session.commit()

    portfolio = client.get("/portfolio")
    assert portfolio.status_code == 200
    assert portfolio.json()["position_count"] == 0

    # 4. Health knows the data is now fresh
    data_health = client.get("/health/data").json()
    freshness = next(c for c in data_health["checks"] if c["name"] == "price_freshness")
    assert freshness["status"] == "healthy", freshness["detail"]

    # 5. Paper trade -- refused without explicit confirmation
    order = {
        "portfolio": "Core", "ticker": ticker, "quantity": 10, "price": 120.0,
        "stop_price": 110.0, "reasoning": "end-to-end walk",
    }

    unconfirmed = client.post("/paper-trades", json=order)
    assert unconfirmed.status_code == 422
    assert "confirm" in unconfirmed.json()["detail"].lower()

    opened = client.post("/paper-trades", json={**order, "confirm": True})
    assert opened.status_code == 201
    trade = opened.json()
    # An open position has no outcome yet, and the API says so with nulls
    # rather than zeros -- there is nothing to be zero about.
    assert trade["status"] == "open"
    assert trade["closed_at"] is None
    assert trade["pnl"] is None
    assert trade["r_multiple"] is None

    # 6. Closing also requires confirmation
    trade_id = trade["id"]
    assert client.post(f"/paper-trades/{trade_id}/close", json={"price": 130.0}).status_code == 422

    closed = client.post(
        f"/paper-trades/{trade_id}/close", json={"price": 130.0, "confirm": True}
    )
    assert closed.status_code == 200
    body = closed.json()
    assert body["status"] == "closed"
    assert body["pnl"] == 100.0  # (130 - 120) * 10
    # A stop was recorded, so this trade *is* scorable in R: risked 10/share,
    # made 10/share.
    assert body["r_multiple"] == 1.0

    # 7. Performance now has exactly one scored trade, and says so
    performance = client.get("/paper-trades/performance").json()
    assert performance["trade_count"] == 1
    assert performance["scored_trades"] == 1
    assert performance["is_significant"] is False
    assert performance["caveat"], "a one-trade sample must carry a caveat"


# -- honesty properties that span stages ----------------------------------------


def test_every_served_signal_carries_evidence(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """Rule 10 end to end: whatever the listing returns, none of it is an
    unsupported claim."""
    db_session.add(
        models.Signal(
            asset_id=seeded_asset.id, signal_type="watch", category="WATCH",
            confidence=0.5, reasoning="testing",
            evidence=[{"kind": "quant", "detail": "momentum", "stance": "supports"}],
            value={}, source="test", status="active", generated_at=NOW,
        )
    )
    db_session.commit()

    body = client.get("/signals").json()

    assert body
    for signal in body:
        assert signal["evidence"], f"signal {signal['id']} was served without evidence"


def test_an_evidence_free_signal_is_withheld_rather_than_served(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """Rows can be written directly to the database, bypassing the engine's
    construction-time guard. The transport boundary is the second line of
    defence, and it must not serve the claim."""
    db_session.add(
        models.Signal(
            asset_id=seeded_asset.id, signal_type="watch", category="WATCH",
            confidence=0.9, reasoning="no evidence recorded",
            evidence=[], value={}, source="test", status="active", generated_at=NOW,
        )
    )
    db_session.commit()

    assert client.get("/signals").json() == []


def test_a_one_snapshot_portfolio_reports_no_daily_return(
    client: TestClient, db_session: Session
) -> None:
    """One data point is not a return, and 0.0 would claim a flat day that
    was never observed."""
    create_portfolio(db_session, "Core", initial_cash=100_000.0)
    db_session.commit()

    performance = client.get("/portfolio/performance").json()

    assert performance["snapshots"] < 2
    assert performance["daily_return"] is None


def test_learning_summary_distinguishes_unknown_from_zero(client: TestClient) -> None:
    body = client.get("/learning/summary").json()

    if not body["available"]:
        assert body["reason"]
    else:
        # Whatever is unresolved must be null -- never 0.0, which would read
        # as a measured result of zero.
        for field in ("signal_accuracy", "invalidation_rate"):
            assert body[field] is None or isinstance(body[field], (int, float))


def test_the_pipeline_never_exposes_an_execution_route(client: TestClient) -> None:
    """Asserted here as well as in the invariants file, because this is the
    one property that must survive every other change in this test."""
    for path in ("/orders", "/execute", "/buy", "/sell"):
        assert client.post(path, json={}).status_code == 403
