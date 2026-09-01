from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import models
from apps.worker.jobs.base import JobContext, JobStatus
from apps.worker.jobs.company_update import CompanyUpdateJob
from apps.worker.jobs.daily_market import DailyMarketUpdateJob
from data.ingestion.errors import ProviderUnavailableError
from data.ingestion.mock_provider import MockProvider
from data.ingestion.registry import ProviderRegistry
from data.storage.price_repository import get_price_bars
from models.base import Base

NOW = dt.datetime(2026, 1, 10, 22, 30, tzinfo=dt.UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("mock", lambda: MockProvider(), synthetic=True)
    return registry


@pytest.fixture
def context(session: Session, registry: ProviderRegistry) -> JobContext:
    return JobContext(session=session, now=NOW, registry=registry)


def _add_asset(session: Session, ticker: str, asset_type: str = "equity") -> models.Asset:
    asset = models.Asset(
        ticker=ticker, exchange="NSE", asset_type=asset_type, name=f"{ticker} Ltd"
    )
    session.add(asset)
    session.flush()
    return asset


# -- daily market update ------------------------------------------------------


def test_daily_update_skips_when_no_assets(context: JobContext) -> None:
    result = DailyMarketUpdateJob().run(context)

    assert result.status is JobStatus.SKIPPED


def test_daily_update_skips_without_a_registry(session: Session) -> None:
    _add_asset(session, "RELIANCE")
    context = JobContext(session=session, now=NOW, registry=None)

    result = DailyMarketUpdateJob().run(context)

    assert result.status is JobStatus.SKIPPED
    assert "registry" in (result.error or "")


def test_daily_update_backfills_prices(context: JobContext) -> None:
    asset = _add_asset(context.session, "RELIANCE")

    result = DailyMarketUpdateJob().run(context)

    assert result.status is JobStatus.SUCCESS
    assert result.items_processed == 1
    assert result.detail["bars_inserted"] > 0
    assert len(get_price_bars(context.session, asset.id)) == result.detail["bars_inserted"]


def test_daily_update_is_idempotent(context: JobContext) -> None:
    """Re-running the same day must insert nothing further."""
    asset = _add_asset(context.session, "RELIANCE")
    job = DailyMarketUpdateJob()

    first = job.run(context)
    after_first = len(get_price_bars(context.session, asset.id))

    second = job.run(context)

    assert second.detail["bars_inserted"] == 0
    assert len(get_price_bars(context.session, asset.id)) == after_first
    assert first.detail["bars_inserted"] > 0


def test_daily_update_fetches_only_the_new_tail_on_a_later_day(context: JobContext) -> None:
    asset = _add_asset(context.session, "RELIANCE")
    job = DailyMarketUpdateJob()
    job.run(context)
    baseline = len(get_price_bars(context.session, asset.id))

    later = JobContext(
        session=context.session,
        now=NOW + dt.timedelta(days=7),
        registry=context.registry,
    )
    result = job.run(later)

    assert 0 < result.detail["bars_inserted"] < baseline
    assert len(get_price_bars(context.session, asset.id)) > baseline


def test_daily_update_reports_partial_when_one_symbol_fails(
    session: Session, registry: ProviderRegistry
) -> None:
    """A single bad symbol must not abort the whole market update."""

    class _PickyProvider(MockProvider):
        def get_historical_prices(self, ticker, start, end, interval="1d"):
            if ticker == "BROKEN":
                raise ProviderUnavailableError("vendor down for this symbol")
            return super().get_historical_prices(ticker, start, end, interval)

    registry.register("picky", lambda: _PickyProvider())
    registry.switch("picky")

    _add_asset(session, "RELIANCE")
    _add_asset(session, "BROKEN")
    context = JobContext(session=session, now=NOW, registry=registry)

    result = DailyMarketUpdateJob().run(context)

    assert result.status is JobStatus.PARTIAL
    assert "BROKEN" in result.detail["failures"]
    assert result.detail["per_ticker"]["RELIANCE"] > 0


def test_daily_update_records_validation_errors(
    session: Session, registry: ProviderRegistry
) -> None:
    from data.ingestion.schemas import PriceBar

    class _CorruptProvider(MockProvider):
        def get_historical_prices(self, ticker, start, end, interval="1d"):
            return [
                PriceBar(
                    ts=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
                    open=100.0,
                    high=90.0,  # inconsistent: high below low
                    low=95.0,
                    close=97.0,
                    volume=10,
                    interval="1d",
                    source="corrupt",
                )
            ]

    registry.register("corrupt", lambda: _CorruptProvider())
    registry.switch("corrupt")
    asset = _add_asset(session, "RELIANCE")
    context = JobContext(session=session, now=NOW, registry=registry)

    DailyMarketUpdateJob().run(context)

    errors = session.scalars(select(models.DataValidationError)).all()
    assert len(errors) == 1
    assert errors[0].code == "high_below_low"
    assert get_price_bars(session, asset.id) == []  # corrupt bar was not stored


def test_daily_update_classifies_regime_with_enough_history(context: JobContext) -> None:
    _add_asset(context.session, "NIFTY", asset_type="index")

    result = DailyMarketUpdateJob().run(context)

    regime = result.detail["regime"]
    assert regime is not None
    assert regime["benchmark"] == "NIFTY"
    stored = context.session.scalars(select(models.MarketRegimeObservation)).all()
    assert len(stored) == 1
    assert stored[0].scope == "benchmark:NIFTY"


def test_daily_update_skips_regime_when_history_is_too_short(
    session: Session, registry: ProviderRegistry
) -> None:
    """An UNKNOWN-everything observation would be noise, so store nothing."""

    class _ShortHistoryProvider(MockProvider):
        def get_historical_prices(self, ticker, start, end, interval="1d"):
            bars = super().get_historical_prices(ticker, start, end, interval)
            return bars[-10:]

    registry.register("short", lambda: _ShortHistoryProvider())
    registry.switch("short")
    _add_asset(session, "RELIANCE")
    context = JobContext(session=session, now=NOW, registry=registry)

    result = DailyMarketUpdateJob().run(context)

    assert result.detail["regime"] is None
    assert session.scalars(select(models.MarketRegimeObservation)).all() == []


# -- company update -----------------------------------------------------------


def test_company_update_writes_profile_and_metrics(context: JobContext) -> None:
    asset = _add_asset(context.session, "RELIANCE")

    result = CompanyUpdateJob().run(context)

    assert result.status is JobStatus.SUCCESS
    company = context.session.scalars(
        select(models.Company).where(models.Company.asset_id == asset.id)
    ).first()
    assert company is not None
    assert company.sector
    assert result.detail["metrics_written"] > 0


def test_company_update_is_idempotent(context: JobContext) -> None:
    asset = _add_asset(context.session, "RELIANCE")
    job = CompanyUpdateJob()

    job.run(context)
    first_metrics = context.session.scalars(select(models.FinancialMetric)).all()
    job.run(context)
    second_metrics = context.session.scalars(select(models.FinancialMetric)).all()

    assert len(second_metrics) == len(first_metrics)
    companies = context.session.scalars(
        select(models.Company).where(models.Company.asset_id == asset.id)
    ).all()
    assert len(companies) == 1


def test_company_update_ignores_non_equity_assets(context: JobContext) -> None:
    _add_asset(context.session, "NIFTY", asset_type="index")

    result = CompanyUpdateJob().run(context)

    assert result.status is JobStatus.SKIPPED
