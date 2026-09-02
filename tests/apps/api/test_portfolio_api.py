from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio, record_buy
from data.storage.price_repository import upsert_price_bars
from paper_trading.tracking import take_snapshot

EXECUTED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)


@pytest.fixture
def portfolio(db_session: Session) -> models.PaperPortfolio:
    portfolio = create_portfolio(db_session, "Core", initial_cash=100_000.0)
    db_session.commit()
    return portfolio


def _price(db_session: Session, asset: models.Asset, close: float, day: int = 1) -> None:
    upsert_price_bars(
        db_session,
        asset.id,
        [
            PriceBar(
                ts=dt.datetime(2026, 3, day, tzinfo=dt.UTC),
                open=close, high=close, low=close, close=close,
                volume=100, interval="1d", source="test",
            )
        ],
    )
    db_session.commit()


def test_portfolio_404_when_none_exists(client: TestClient) -> None:
    response = client.get("/portfolio")

    assert response.status_code == 404
    assert "No paper portfolio" in response.json()["detail"]


def test_portfolio_all_cash(client: TestClient, portfolio: models.PaperPortfolio) -> None:
    response = client.get("/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert body["cash"] == 100_000.0
    assert body["total_value"] == 100_000.0
    assert body["exposure"] == 0.0
    assert body["position_count"] == 0


def test_portfolio_with_a_priced_position(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()
    _price(db_session, seeded_asset, 1200.0)

    body = client.get("/portfolio").json()

    assert body["cash"] == pytest.approx(90_000.0)
    assert body["positions_value"] == pytest.approx(12_000.0)
    assert body["total_value"] == pytest.approx(102_000.0)
    assert body["unrealized_pnl"] == pytest.approx(2_000.0)
    assert body["unpriced_positions"] == 0


def test_unpriced_position_is_flagged_not_valued_at_cost(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    """Rule 4: a stale cost must not be presented as a current value."""
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()

    body = client.get("/portfolio").json()
    positions = client.get("/portfolio/positions").json()

    assert body["unpriced_positions"] == 1
    assert body["positions_value"] == 0.0
    assert positions[0]["unpriced"] is True
    assert positions[0]["current_price"] is None


def test_positions_endpoint(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()
    _price(db_session, seeded_asset, 1100.0)

    positions = client.get("/portfolio/positions").json()

    assert len(positions) == 1
    assert positions[0]["ticker"] == "RELIANCE"
    assert positions[0]["allocation"] == pytest.approx(11_000 / 101_000)


def test_performance_without_snapshots_is_honest(
    client: TestClient, portfolio: models.PaperPortfolio
) -> None:
    body = client.get("/portfolio/performance").json()

    assert body["snapshots"] == 0
    assert body["daily_return"] is None  # one point is not a return
    assert "not yet meaningful" in body["caveat"]


def test_performance_with_history(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    record_buy(db_session, portfolio, seeded_asset, quantity=50, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()
    for day, close in ((1, 1000.0), (2, 1200.0), (3, 900.0)):
        _price(db_session, seeded_asset, close, day=day)
        take_snapshot(db_session, portfolio, as_of=dt.date(2026, 3, day))
    db_session.commit()

    body = client.get("/portfolio/performance").json()

    assert body["snapshots"] == 3
    assert body["daily_return"] is not None
    assert body["max_drawdown"] < 0
    assert body["fully_priced"] is True


def test_exposure_breaks_down_by_sector_and_asset(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()
    _price(db_session, seeded_asset, 1000.0)

    body = client.get("/portfolio/exposure").json()

    assert body["gross_exposure"] == pytest.approx(0.1)
    assert body["cash_weight"] == pytest.approx(0.9)
    assert body["by_sector"][0]["label"] == "Energy"  # from the seeded company
    assert body["by_asset"][0]["label"] == "RELIANCE"


def test_allocation_endpoint(
    client: TestClient, db_session: Session, portfolio: models.PaperPortfolio,
    seeded_asset: models.Asset,
) -> None:
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=EXECUTED_AT)
    db_session.commit()
    _price(db_session, seeded_asset, 1000.0)

    body = client.get("/portfolio/allocation").json()

    assert body[0]["label"] == "RELIANCE"
    assert body[0]["weight"] == pytest.approx(0.1)


def test_named_portfolio_lookup_and_404(
    client: TestClient, portfolio: models.PaperPortfolio
) -> None:
    assert client.get("/portfolio", params={"name": "Core"}).status_code == 200
    assert client.get("/portfolio", params={"name": "Nope"}).status_code == 404


def test_legacy_summary_endpoint_still_works(client: TestClient) -> None:
    assert client.get("/portfolio/summary").status_code == 200
