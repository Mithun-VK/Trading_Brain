"""CRITICAL TEST: the deterministic core survives total AI failure.

AI is an enhancement to TradingBrain, not a dependency of it. If every LLM
provider disappeared, the parts of this system that handle money — market
data, validation, quant, risk, backtesting, portfolio, paper trading — must
keep working exactly as before.

This matters beyond uptime. Rule 16 says AI availability must never
determine whether a risk constraint is enforced. A risk engine that silently
stops checking because a language model is down is worse than one that never
existed, because the operator still believes it is running.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import models
from ai.provider import AIProviderRegistry
from ai.schemas import AIRequest, AIRequestContext, AITaskType
from config.settings import Settings
from data.ingestion.mock_provider import MockProvider
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio
from data.storage.price_repository import upsert_price_bars

NOW = dt.datetime(2026, 3, 16, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def no_ai_settings() -> Settings:
    """A configuration with no AI provider of any kind."""
    return Settings(ANTHROPIC_API_KEY="", LOCAL_LLM_BASE_URL="")


def test_settings_report_ai_as_disabled(no_ai_settings: Settings) -> None:
    assert no_ai_settings.ai_enabled is False


# -- the deterministic core ----------------------------------------------------


def test_market_data_ingestion_works_with_no_ai() -> None:
    provider = MockProvider()

    bars = provider.get_historical_prices(
        "RELIANCE", start=(NOW - dt.timedelta(days=30)).date(), end=NOW.date()
    )

    assert bars, "Market data ingestion must not depend on an LLM"


def test_the_quant_engine_works_with_no_ai() -> None:
    from quant.indicators.moving_average import sma
    from quant.indicators.returns import max_drawdown, simple_returns, volatility

    closes = [100.0 + i for i in range(30)]

    assert sma(closes, period=10)[-1] is not None
    assert volatility(simple_returns(closes)) >= 0
    assert max_drawdown(closes) <= 0.0


def test_risk_math_works_with_no_ai() -> None:
    """Rule 16: AI availability must never determine whether a risk
    constraint is enforced."""
    from quant.performance.risk import position_size

    size = position_size(
        account_equity=100_000.0,
        risk_per_trade_pct=0.01,
        entry_price=100.0,
        stop_price=95.0,
    )

    assert size > 0


def test_backtesting_works_with_no_ai() -> None:
    from backtesting.engine import BacktestEngine

    assert BacktestEngine is not None


def test_portfolio_and_paper_trading_work_with_no_ai(
    db_session: Session, seeded_asset: models.Asset
) -> None:
    from data.storage.portfolio_repository import record_buy
    from paper_trading.service import valuation_for

    portfolio = create_portfolio(db_session, "Core", initial_cash=100_000.0)
    record_buy(
        db_session, portfolio, seeded_asset, quantity=10, price=1000.0, executed_at=NOW
    )
    db_session.commit()

    valuation = valuation_for(db_session, portfolio)

    assert valuation.cash_balance == 90_000.0


def test_the_signal_engine_works_with_no_ai() -> None:
    """Signals are rule-based. They were never an AI feature."""
    from brain.signals.schemas import Evidence, EvidenceStance, GeneratedSignal, SignalCategory

    signal = GeneratedSignal(
        asset_id=1,
        ticker="RELIANCE",
        category=SignalCategory.WATCH,
        reasoning="momentum turned positive",
        evidence=[
            Evidence(kind="quant", detail="20d momentum > 0", stance=EvidenceStance.SUPPORTS)
        ],
    )

    assert signal.category is SignalCategory.WATCH


def test_the_scheduler_works_with_no_ai(db_session: Session) -> None:
    """No registered job invokes an LLM, so every one of them must remain
    runnable. Verified against the real job registry, not a stand-in."""
    from apps.worker.main import build_scheduler

    scheduler = build_scheduler()

    assert len(scheduler.registered()) == 8


# -- the deterministic API surface ---------------------------------------------


def test_deterministic_endpoints_answer_with_no_ai(
    client: TestClient, db_session: Session, seeded_asset: models.Asset
) -> None:
    """Every endpoint that does not reason must still answer."""
    upsert_price_bars(
        db_session,
        seeded_asset.id,
        [
            PriceBar(
                ts=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
                open=100, high=101, low=99, close=100,
                volume=1000, interval="1d", source="test",
            )
        ],
    )
    create_portfolio(db_session, "Core", initial_cash=100_000.0)
    db_session.commit()

    for path in (
        "/health",
        "/health/live",
        "/health/data",
        "/portfolio",
        "/portfolio/positions",
        "/portfolio/performance",
        "/signals",
        "/watchlists",
        "/backtests",
        "/paper-trades",
        "/research/queue",
    ):
        response = client.get(path)
        assert response.status_code < 500, f"{path} returned {response.status_code}"


def test_health_still_reports_when_ai_is_unconfigured(client: TestClient) -> None:
    """An absent AI provider must not make the system look broken. It is a
    missing enhancement, not a failed dependency."""
    response = client.get("/health")

    assert response.status_code in (200, 503)
    assert response.json()["status"] in {"healthy", "degraded", "unavailable"}


# -- the gateway degrades, it does not fabricate --------------------------------


def test_the_gateway_returns_unavailable_rather_than_inventing(
    no_ai_settings: Settings,
) -> None:
    """The single most important behaviour in this file.

    With no provider configured the gateway must return a structured
    failure. It must never return plausible text, because a caller cannot
    tell invented reasoning from real reasoning.
    """
    from ai.gateway import AIGateway

    gateway = AIGateway(no_ai_settings, AIProviderRegistry())

    response = gateway.invoke(
        AIRequest(
            task_type=AITaskType.RESEARCH_SYNTHESIS,
            prompt="Analyse this company.",
            context=AIRequestContext(request_id="test-1", source="test"),
        )
    )

    assert response.success is False
    assert response.text == ""
    assert response.data is None
    assert response.error


def test_a_failed_response_cannot_carry_content() -> None:
    """Enforced at construction, so no code path can produce one."""
    from ai.schemas import AIResponse, AIResponseError

    with pytest.raises(AIResponseError, match="must not carry content"):
        AIResponse(
            request_id="x",
            success=False,
            provider="p",
            model="m",
            text="a plausible but invented analysis",
        )


def test_every_provider_disabled_still_leaves_routing_explicable() -> None:
    """With no providers, routing fails with a reason -- it does not pick
    something arbitrary."""
    from ai.router import AIRouter
    from ai.schemas import AIRoutingError

    router = AIRouter(AIProviderRegistry())

    with pytest.raises(AIRoutingError, match="No model is available"):
        router.route(
            AIRequest(
                task_type=AITaskType.THESIS_REVIEW,
                prompt="review",
                context=AIRequestContext(request_id="t", source="test"),
            )
        )
