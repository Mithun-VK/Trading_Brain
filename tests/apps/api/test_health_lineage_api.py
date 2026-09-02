from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio, record_buy
from data.storage.price_repository import upsert_price_bars
from data.storage.watchlist_repository import add_item, create_watchlist
from observability.checks import Status, check_portfolio_consistency, check_price_freshness

NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.UTC)


def _price(db_session: Session, asset: models.Asset, close: float, when: dt.datetime) -> None:
    upsert_price_bars(
        db_session,
        asset.id,
        [
            PriceBar(
                ts=when, open=close, high=close, low=close, close=close,
                volume=100, interval="1d", source="test",
            )
        ],
    )
    db_session.commit()


# -- health -------------------------------------------------------------------


def test_health_sections_are_addressable(client: TestClient) -> None:
    for path in ("/health/dependencies", "/health/data", "/health/jobs"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] in {"healthy", "degraded", "unavailable"}
        assert response.json()["checks"]


def test_database_check_passes_on_a_live_session(client: TestClient) -> None:
    body = client.get("/health/dependencies").json()

    database = next(c for c in body["checks"] if c["name"] == "database")
    assert database["status"] == "healthy"


def test_unconfigured_optional_integrations_are_degraded_not_unavailable() -> None:
    """The system genuinely works without them; calling that a failure
    would train you to ignore health output.

    Settings are constructed explicitly rather than read through the API so
    the assertion doesn't depend on whatever the developer's .env happens
    to contain.
    """
    from config.settings import Settings
    from observability.checks import check_claude, check_obsidian

    blank = Settings(OBSIDIAN_API_KEY="", ANTHROPIC_API_KEY="")

    assert check_obsidian(blank).status is Status.DEGRADED
    assert check_claude(blank).status is Status.DEGRADED


def test_configured_claude_is_healthy_without_being_probed() -> None:
    """A health endpoint that bills you per poll is a bad health endpoint."""
    from config.settings import Settings
    from observability.checks import check_claude

    check = check_claude(Settings(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="m"))

    assert check.status is Status.HEALTHY
    assert "Not probed" in check.detail


def test_synthetic_provider_in_production_is_degraded() -> None:
    """Rule 4: generated numbers must never pass as real in production."""
    from config.settings import Settings
    from observability.checks import check_market_data

    check = check_market_data(
        Settings(MARKET_DATA_PROVIDER="mock", APP_ENV="production")
    )

    assert check.status is Status.DEGRADED
    assert "synthetic" in check.detail


def test_synthetic_provider_outside_production_is_fine() -> None:
    from config.settings import Settings
    from observability.checks import check_market_data

    check = check_market_data(
        Settings(MARKET_DATA_PROVIDER="mock", APP_ENV="development")
    )

    assert check.status is Status.HEALTHY


def test_missing_prices_degrade_data_health(client: TestClient) -> None:
    body = client.get("/health/data").json()

    freshness = next(c for c in body["checks"] if c["name"] == "price_freshness")
    assert freshness["status"] == "degraded"
    assert "No price data stored" in freshness["detail"]


def test_fresh_prices_are_healthy(db_session: Session, seeded_asset: models.Asset) -> None:
    now = dt.datetime.now(dt.UTC)
    _price(db_session, seeded_asset, 100.0, now - dt.timedelta(days=1))

    check = check_price_freshness(db_session, now)

    assert check.status is Status.HEALTHY


def test_very_stale_prices_are_unavailable(
    db_session: Session, seeded_asset: models.Asset
) -> None:
    now = dt.datetime.now(dt.UTC)
    _price(db_session, seeded_asset, 100.0, now - dt.timedelta(days=30))

    check = check_price_freshness(db_session, now)

    assert check.status is Status.UNAVAILABLE


def test_empty_watchlists_degrade(client: TestClient, db_session: Session) -> None:
    create_watchlist(db_session, "Empty")
    db_session.commit()

    body = client.get("/health/data").json()

    watchlists = next(c for c in body["checks"] if c["name"] == "watchlists")
    assert watchlists["status"] == "degraded"
    assert "no assets" in watchlists["detail"]


def test_populated_watchlist_is_healthy(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    watchlist = create_watchlist(db_session, "AI")
    add_item(db_session, watchlist, seeded_asset)
    db_session.commit()

    body = client.get("/health/data").json()

    watchlists = next(c for c in body["checks"] if c["name"] == "watchlists")
    assert watchlists["status"] == "healthy"


def test_portfolio_consistency_detects_ledger_drift(
    db_session: Session, seeded_asset: models.Asset
) -> None:
    """Cash that disagrees with its own ledger is a correctness bug."""
    portfolio = create_portfolio(db_session, "Core", initial_cash=100_000.0)
    record_buy(db_session, portfolio, seeded_asset, quantity=10, price=1000.0,
               executed_at=NOW)
    db_session.commit()
    assert check_portfolio_consistency(db_session).status is Status.HEALTHY

    portfolio.cash_balance = 12_345.0  # corrupt the balance out from under the ledger
    db_session.commit()

    check = check_portfolio_consistency(db_session)
    assert check.status is Status.UNAVAILABLE
    assert check.data["mismatches"]


def test_no_job_history_is_degraded(client: TestClient) -> None:
    body = client.get("/health/jobs").json()

    scheduler = next(c for c in body["checks"] if c["name"] == "scheduler")
    assert scheduler["status"] == "degraded"
    assert "worker running" in scheduler["detail"]


def test_a_job_that_failed_then_succeeded_is_not_currently_failing(
    client: TestClient, db_session: Session
) -> None:
    now = dt.datetime.now(dt.UTC)
    db_session.add(
        models.JobRun(
            job_name="daily_market_update", status="failed", trigger="scheduled",
            started_at=now - dt.timedelta(hours=2), finished_at=now - dt.timedelta(hours=2),
        )
    )
    db_session.add(
        models.JobRun(
            job_name="daily_market_update", status="success", trigger="scheduled",
            started_at=now - dt.timedelta(hours=1), finished_at=now - dt.timedelta(hours=1),
        )
    )
    db_session.commit()

    body = client.get("/health/jobs").json()

    failures = next(c for c in body["checks"] if c["name"] == "job_failures")
    assert failures["status"] == "degraded"  # noted, but not currently broken
    assert failures["data"]["currently_failing"] == []


def test_a_currently_failing_job_is_unavailable(
    client: TestClient, db_session: Session
) -> None:
    now = dt.datetime.now(dt.UTC)
    db_session.add(
        models.JobRun(
            job_name="daily_market_update", status="failed", trigger="scheduled",
            started_at=now - dt.timedelta(hours=1), finished_at=now,
        )
    )
    db_session.commit()

    body = client.get("/health/jobs").json()

    failures = next(c for c in body["checks"] if c["name"] == "job_failures")
    assert failures["status"] == "unavailable"
    assert "daily_market_update" in failures["data"]["currently_failing"]


# -- lineage ------------------------------------------------------------------


def _signal(db_session: Session, asset: models.Asset) -> models.Signal:
    signal = models.Signal(
        asset_id=asset.id, signal_type="accumulate", category="ACCUMULATE",
        confidence=0.8, reasoning="thesis intact, bullish regime",
        evidence=[{"kind": "quant", "detail": "momentum positive", "stance": "supports"}],
        value={}, source="brain.signals.engine", status="active", generated_at=NOW,
    )
    db_session.add(signal)
    db_session.commit()
    return signal


def test_signal_lineage_answers_the_provenance_questions(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    db_session.add(
        models.MarketRegimeObservation(
            observed_at=NOW - dt.timedelta(days=1), regime="BULLISH",
            volatility_regime="LOW_VOLATILITY", risk_regime="RISK_ON",
        )
    )
    db_session.add(
        models.Thesis(asset_id=seeded_asset.id, title="Upcycle", status="active",
                      current_assessment="THESIS_INTACT")
    )
    db_session.commit()
    _price(db_session, seeded_asset, 1000.0, NOW - dt.timedelta(days=1))
    signal = _signal(db_session, seeded_asset)

    body = client.get(f"/lineage/signals/{signal.id}").json()

    stages = {node["stage"]: node for node in body["chain"]}
    assert set(stages) == {
        "market_data", "regime", "research", "thesis", "signal", "paper_trade"
    }
    assert stages["regime"]["recorded"] is True
    assert "BULLISH" in stages["regime"]["summary"]
    assert stages["thesis"]["recorded"] is True
    assert body["evidence"]


def test_lineage_marks_missing_links_as_not_recorded(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """An invented provenance is worse than a missing one."""
    signal = _signal(db_session, seeded_asset)

    body = client.get(f"/lineage/signals/{signal.id}").json()

    stages = {node["stage"]: node for node in body["chain"]}
    assert stages["research"]["recorded"] is False
    assert "No research document" in stages["research"]["summary"]
    assert stages["paper_trade"]["recorded"] is False


def test_trade_lineage_explains_missing_risk(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    trade = models.Trade(
        asset_id=seeded_asset.id, direction="long", timeframe="1d",
        entry_price=1000, position_size=10, status="open", opened_at=NOW,
    )
    db_session.add(trade)
    db_session.commit()

    body = client.get(f"/lineage/trades/{trade.id}").json()

    risk = next(n for n in body["chain"] if n["stage"] == "risk")
    assert risk["recorded"] is False
    assert "invented risk" in risk["summary"]


def test_thesis_lineage_returns_the_review_history(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    thesis = models.Thesis(
        asset_id=seeded_asset.id, title="Upcycle", status="active",
        current_assessment="THESIS_WEAKENED",
    )
    db_session.add(thesis)
    db_session.flush()
    db_session.add(
        models.ThesisReviewRecord(
            thesis_id=thesis.id, asset_id=seeded_asset.id,
            previous_assessment="THESIS_INTACT", assessment="THESIS_WEAKENED",
            reviewed_at=NOW, confidence=0.6, reasoning="margins compressed",
        )
    )
    db_session.commit()

    body = client.get(f"/lineage/theses/{thesis.id}").json()

    assert body["history_recorded"] is True
    assert body["review_history"][0]["to"] == "THESIS_WEAKENED"
    assert body["review_history"][0]["reasoning"] == "margins compressed"


def test_learning_lineage_names_its_source_records(client: TestClient) -> None:
    client.post("/learning/reports/generate", json={"kind": "monthly", "as_of": "2026-03-05"})

    body = client.get("/lineage/learning").json()

    assert body["thesis_accuracy"]["source_table"] == "thesis_review_records"
    assert "excluded_because" in body["signal_accuracy"]
    assert body["research_outcomes"]["is_accuracy_score"] is False


def test_lineage_404s(client: TestClient) -> None:
    assert client.get("/lineage/signals/999999").status_code == 404
    assert client.get("/lineage/trades/999999").status_code == 404
    assert client.get("/lineage/theses/999999").status_code == 404
    assert client.get("/lineage/learning").status_code == 404
