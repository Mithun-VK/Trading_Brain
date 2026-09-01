from __future__ import annotations

from fastapi.testclient import TestClient

import models


def test_get_asset_404_for_unknown_ticker(client: TestClient) -> None:
    response = client.get("/assets/UNKNOWN")

    assert response.status_code == 404


def test_get_asset_returns_company_data(client: TestClient, seeded_asset: models.Asset) -> None:
    response = client.get("/assets/RELIANCE")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE"
    assert body["sector"] == "Energy"


def test_get_market_quote(client: TestClient) -> None:
    response = client.get("/market/RELIANCE")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE"
    assert body["source"] == "mock"
    assert body["price"] > 0


def test_get_market_regime_404_when_none_recorded(client: TestClient) -> None:
    response = client.get("/market/regime")

    assert response.status_code == 404


def test_get_market_regime_returns_latest(client: TestClient, db_session) -> None:
    import datetime as dt

    db_session.add(
        models.MarketRegimeObservation(
            observed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            regime="BULLISH",
            volatility_regime="LOW_VOLATILITY",
            risk_regime="RISK_ON",
        )
    )
    db_session.commit()

    response = client.get("/market/regime")

    assert response.status_code == 200
    assert response.json()["trend_regime"] == "BULLISH"


def test_get_analysis_returns_quant_summary(client: TestClient) -> None:
    response = client.get("/analysis/RELIANCE")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE"
    assert "last_close" in body["quant_summary"]


def test_post_research_404_for_unknown_ticker(client: TestClient) -> None:
    response = client.post("/research/UNKNOWN")

    assert response.status_code == 404


def test_post_research_creates_and_publishes_analysis(
    client: TestClient, seeded_asset: models.Asset, knowledge_store
) -> None:
    response = client.post("/research/RELIANCE")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE"
    assert body["summary"] == "test summary"
    assert any(p.startswith("08 Research/") for p in knowledge_store.notes)


def test_get_thesis_404_when_none_active(client: TestClient, seeded_asset: models.Asset) -> None:
    response = client.get("/thesis/RELIANCE")

    assert response.status_code == 404


def test_get_thesis_returns_active_thesis(client: TestClient, seeded_thesis: models.Thesis) -> None:
    response = client.get("/thesis/RELIANCE")

    assert response.status_code == 200
    assert response.json()["current_assessment"] == "THESIS_INTACT"


def test_post_thesis_review_applies_and_audits(
    client: TestClient, seeded_thesis: models.Thesis, knowledge_store
) -> None:
    response = client.post("/thesis/RELIANCE/review")

    assert response.status_code == 200
    assert response.json()["assessment"] == "THESIS_INTACT"
    note_content = knowledge_store.notes[seeded_thesis.obsidian_note_path]
    assert "THESIS_INTACT -> THESIS_INTACT" in note_content


def test_create_and_list_trades(client: TestClient, seeded_asset: models.Asset) -> None:
    payload = {
        "ticker": "RELIANCE",
        "direction": "long",
        "strategy_name": "breakout",
        "timeframe": "1d",
        "entry_price": 100,
        "stop_price": 95,
        "risk_amount": 500,
        "position_size": 100,
        "opened_at": "2026-01-01T00:00:00Z",
    }

    create_response = client.post("/trades", json=payload)
    assert create_response.status_code == 201
    trade_id = create_response.json()["id"]

    list_response = client.get("/trades", params={"ticker": "RELIANCE"})
    assert list_response.status_code == 200
    assert any(t["id"] == trade_id for t in list_response.json())


def test_create_trade_404_for_unknown_ticker(client: TestClient) -> None:
    payload = {
        "ticker": "UNKNOWN",
        "direction": "long",
        "timeframe": "1d",
        "entry_price": 100,
        "stop_price": 95,
        "risk_amount": 500,
        "position_size": 100,
        "opened_at": "2026-01-01T00:00:00Z",
    }

    response = client.post("/trades", json=payload)

    assert response.status_code == 404


def test_review_trade(client: TestClient, seeded_trade: models.Trade) -> None:
    response = client.post(f"/trades/{seeded_trade.id}/review")

    assert response.status_code == 200
    assert response.json()["overall"]["trade_count"] == 1


def test_review_trade_404_for_unknown_id(client: TestClient) -> None:
    response = client.post("/trades/999999/review")

    assert response.status_code == 404


def test_portfolio_summary(client: TestClient, seeded_trade: models.Trade) -> None:
    response = client.get("/portfolio/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["trades_by_status"]["closed"] == 1
    assert body["open_trade_count"] == 0
