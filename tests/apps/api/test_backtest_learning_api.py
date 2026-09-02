from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from data.storage.portfolio_repository import create_portfolio


def _run_payload(**overrides) -> dict:
    payload = {
        "strategy": "buy_and_hold",
        "tickers": ["RELIANCE"],
        "start": "2024-01-01",
        "end": "2024-06-30",
    }
    payload.update(overrides)
    return payload


# -- backtests ----------------------------------------------------------------


def test_run_backtest_returns_metrics(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post("/backtests/run", json=_run_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["strategy"] == "buy_and_hold"
    for key in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown",
                "win_rate", "profit_factor", "expectancy", "trade_count"):
        assert key in body["metrics"]
    assert body["equity_curve"]
    assert body["parameters"]["initial_cash"] == 100_000.0


def test_backtest_is_persisted_and_retrievable(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    created = client.post("/backtests/run", json=_run_payload()).json()

    fetched = client.get(f"/backtests/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["metrics"] == created["metrics"]
    assert len(client.get("/backtests").json()) == 1


def test_backtest_is_reproducible_through_the_api(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    """Same request, same numbers -- determinism survives the transport."""
    first = client.post("/backtests/run", json=_run_payload()).json()
    second = client.post("/backtests/run", json=_run_payload()).json()

    assert first["metrics"] == second["metrics"]
    assert first["id"] != second["id"]


def test_ma_cross_strategy_accepts_parameters(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post(
        "/backtests/run", json=_run_payload(strategy="ma_cross", fast=5, slow=20)
    )

    assert response.status_code == 201
    assert response.json()["parameters"]["fast"] == 5


def test_end_before_start_is_rejected(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post(
        "/backtests/run", json=_run_payload(start="2024-06-30", end="2024-01-01")
    )

    assert response.status_code == 422


def test_unknown_ticker_is_rejected(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_run_payload(tickers=["NOSUCH"]))

    assert response.status_code == 404


def test_unknown_strategy_is_rejected(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post("/backtests/run", json=_run_payload(strategy="magic"))

    assert response.status_code == 422


def test_inverted_ma_windows_are_rejected(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post(
        "/backtests/run", json=_run_payload(strategy="ma_cross", fast=30, slow=10)
    )

    assert response.status_code == 422


def test_excessive_range_is_rejected(
    client: TestClient, seeded_asset: models.Asset
) -> None:
    response = client.post(
        "/backtests/run", json=_run_payload(start="1990-01-01", end="2024-01-01")
    )

    assert response.status_code == 422


def test_unknown_backtest_id_is_404(client: TestClient) -> None:
    assert client.get("/backtests/999999").status_code == 404


# -- paper trades -------------------------------------------------------------


@pytest.fixture
def portfolio(db_session: Session) -> models.PaperPortfolio:
    portfolio = create_portfolio(db_session, "Core", initial_cash=100_000.0)
    db_session.commit()
    return portfolio


def _trade_payload(**overrides) -> dict:
    payload = {
        "portfolio": "Core",
        "ticker": "RELIANCE",
        "quantity": 10,
        "price": 1000.0,
        "stop_price": 900.0,
        "reasoning": "thesis intact, bullish regime",
        "confirm": True,
    }
    payload.update(overrides)
    return payload


def test_opening_a_paper_trade_requires_explicit_confirmation(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    """Rule 7: never a side effect."""
    response = client.post("/paper-trades", json=_trade_payload(confirm=False))

    assert response.status_code == 422
    assert "confirm=true" in response.json()["detail"]
    assert client.get("/paper-trades").json() == []


def test_confirmed_paper_trade_opens(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    response = client.post("/paper-trades", json=_trade_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "open"
    assert body["ticker"] == "RELIANCE"
    assert body["risk_amount"] == pytest.approx(1000.0)


def test_closing_requires_confirmation(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    trade = client.post("/paper-trades", json=_trade_payload()).json()

    response = client.post(
        f"/paper-trades/{trade['id']}/close", json={"price": 1200.0, "confirm": False}
    )

    assert response.status_code == 422
    assert client.get(f"/paper-trades/{trade['id']}").json()["status"] == "open"


def test_closing_records_outcome_and_r_multiple(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    trade = client.post("/paper-trades", json=_trade_payload()).json()

    closed = client.post(
        f"/paper-trades/{trade['id']}/close", json={"price": 1200.0, "confirm": True}
    ).json()

    assert closed["status"] == "closed"
    assert closed["result"] == "win"
    assert closed["r_multiple"] == pytest.approx(2.0)
    assert closed["holding_period_days"] is not None


def test_a_trade_without_a_stop_gets_no_r_multiple(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    trade = client.post("/paper-trades", json=_trade_payload(stop_price=None)).json()

    closed = client.post(
        f"/paper-trades/{trade['id']}/close", json={"price": 1200.0, "confirm": True}
    ).json()

    assert closed["result"] == "win"
    assert closed["r_multiple"] is None
    assert closed["pnl"] is None  # not reconstructible without recorded risk


def test_closing_twice_conflicts(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    trade = client.post("/paper-trades", json=_trade_payload()).json()
    client.post(f"/paper-trades/{trade['id']}/close", json={"price": 1200.0, "confirm": True})

    response = client.post(
        f"/paper-trades/{trade['id']}/close", json={"price": 1300.0, "confirm": True}
    )

    assert response.status_code == 409


def test_insufficient_cash_is_rejected(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    response = client.post("/paper-trades", json=_trade_payload(quantity=100_000))

    assert response.status_code == 409


def test_unknown_signal_reference_is_rejected(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    response = client.post("/paper-trades", json=_trade_payload(signal_id=999999))

    assert response.status_code == 404


def test_paper_trade_performance_flags_small_samples(
    client: TestClient, portfolio: models.PaperPortfolio, seeded_asset: models.Asset
) -> None:
    trade = client.post("/paper-trades", json=_trade_payload()).json()
    client.post(f"/paper-trades/{trade['id']}/close", json={"price": 1200.0, "confirm": True})

    body = client.get("/paper-trades/performance").json()

    assert body["scored_trades"] == 1
    assert body["is_significant"] is False
    assert "too small" in body["caveat"]


def test_paper_trade_performance_empty_state(client: TestClient) -> None:
    body = client.get("/paper-trades/performance").json()

    assert body["trade_count"] == 0
    assert body["is_significant"] is False


# -- learning -----------------------------------------------------------------


def test_learning_reports_empty(client: TestClient) -> None:
    assert client.get("/learning/reports").json() == []
    summary = client.get("/learning/summary").json()
    assert summary["available"] is False


def test_generate_learning_report(client: TestClient) -> None:
    response = client.post(
        "/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "monthly"
    assert body["period_start"] == "2026-02-01"
    assert "signal_accuracy" in body["metrics"]


def test_generated_report_preserves_honesty_fields(client: TestClient) -> None:
    """Sample sizes, significance and the research caveat must survive transport."""
    body = client.post(
        "/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"}
    ).json()

    signal_overall = body["metrics"]["signal_accuracy"]["overall"]
    assert "sample_size" in signal_overall
    assert "is_significant" in signal_overall
    assert signal_overall["accuracy"] is None  # nothing resolved -> unknown, not 0.0

    research = body["metrics"]["research_outcomes"]
    assert research["is_accuracy_score"] is False
    assert "falsifiable" in research["why_not_accuracy"]

    excluded = body["metrics"]["signal_accuracy"]["excluded_categories"]
    assert "WATCH" in excluded


def test_regenerating_a_period_does_not_duplicate(client: TestClient) -> None:
    client.post("/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"})
    client.post("/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"})

    assert len(client.get("/learning/reports").json()) == 1


def test_invalid_review_kind_is_rejected(client: TestClient) -> None:
    response = client.post("/learning/reports/generate", json={"kind": "hourly"})

    assert response.status_code == 422


def test_get_report_by_id_and_404(client: TestClient) -> None:
    created = client.post(
        "/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"}
    ).json()

    assert client.get(f"/learning/reports/{created['id']}").status_code == 200
    assert client.get("/learning/reports/999999").status_code == 404


def test_learning_summary_distinguishes_unknown_from_zero(client: TestClient) -> None:
    client.post("/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"})

    summary = client.get("/learning/summary").json()

    assert summary["available"] is True
    assert summary["signal_accuracy"] is None  # unknown, not 0.0
    assert summary["research_is_accuracy_score"] is False


def test_review_kinds_endpoint(client: TestClient) -> None:
    kinds = client.get("/learning/kinds").json()["kinds"]

    assert set(kinds) == {"monthly", "quarterly", "annual"}


def test_no_execution_endpoints_exist(client: TestClient) -> None:
    """The blanket guard still holds across the expanded API surface."""
    for path in ("/orders", "/execute", "/buy", "/sell"):
        assert client.post(path).status_code == 403
