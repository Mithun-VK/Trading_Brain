from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from data.ingestion.mock_provider import MockProvider
from data.ingestion.schemas import Interval, PriceBar
from data.normalization.validation import validate_price_bars
from data.storage.price_repository import (
    get_close_series,
    get_latest_bar_ts,
    get_price_bars,
    normalize_ts,
    upsert_price_bars,
)
from data.storage.validation_repository import (
    get_recent_validation_errors,
    save_validation_report,
)
from models.base import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def asset(session: Session) -> models.Asset:
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    return asset


def _bar(day: int, close: float = 100.0, interval: str = "1d") -> PriceBar:
    return PriceBar(
        ts=dt.datetime(2026, 1, day, tzinfo=dt.UTC),
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        volume=1000,
        interval=interval,
        source="mock",
    )


def test_upsert_inserts_new_bars(session: Session, asset: models.Asset) -> None:
    result = upsert_price_bars(session, asset.id, [_bar(1), _bar(2)])

    assert result.inserted == 2
    assert result.skipped == 0
    assert len(get_price_bars(session, asset.id)) == 2


def test_upsert_is_idempotent(session: Session, asset: models.Asset) -> None:
    """Re-running an ingestion job must be a no-op, not a duplicate or a crash."""
    bars = [_bar(1), _bar(2)]
    upsert_price_bars(session, asset.id, bars)
    session.commit()

    second = upsert_price_bars(session, asset.id, bars)
    session.commit()

    assert second.inserted == 0
    assert second.skipped == 2
    assert len(get_price_bars(session, asset.id)) == 2


def test_upsert_adds_only_the_new_tail(session: Session, asset: models.Asset) -> None:
    upsert_price_bars(session, asset.id, [_bar(1), _bar(2)])
    session.commit()

    result = upsert_price_bars(session, asset.id, [_bar(2), _bar(3), _bar(4)])

    assert result.inserted == 2
    assert result.skipped == 1


def test_upsert_deduplicates_within_a_single_batch(session: Session, asset: models.Asset) -> None:
    result = upsert_price_bars(session, asset.id, [_bar(1), _bar(1), _bar(2)])

    assert result.inserted == 2
    assert result.skipped == 1


def test_intervals_are_stored_independently(session: Session, asset: models.Asset) -> None:
    upsert_price_bars(session, asset.id, [_bar(1, interval="1d")])
    upsert_price_bars(session, asset.id, [_bar(1, interval="1wk")])
    upsert_price_bars(session, asset.id, [_bar(1, interval="1mo")])
    session.commit()

    assert len(get_price_bars(session, asset.id, interval="1d")) == 1
    assert len(get_price_bars(session, asset.id, interval="1wk")) == 1
    assert len(get_price_bars(session, asset.id, interval="1mo")) == 1


def test_get_latest_bar_ts_anchors_incremental_fetches(
    session: Session, asset: models.Asset
) -> None:
    assert get_latest_bar_ts(session, asset.id, "1d") is None

    upsert_price_bars(session, asset.id, [_bar(1), _bar(5), _bar(3)])
    session.commit()

    latest = get_latest_bar_ts(session, asset.id, "1d")
    assert latest is not None
    assert normalize_ts(latest) == dt.datetime(2026, 1, 5)


def test_get_close_series_is_chronological(session: Session, asset: models.Asset) -> None:
    unordered = [_bar(3, close=30.0), _bar(1, close=10.0), _bar(2, close=20.0)]
    upsert_price_bars(session, asset.id, unordered)
    session.commit()

    assert get_close_series(session, asset.id) == [10.0, 20.0, 30.0]


def test_get_close_series_respects_limit(session: Session, asset: models.Asset) -> None:
    upsert_price_bars(session, asset.id, [_bar(d, close=float(d)) for d in range(1, 6)])
    session.commit()

    assert get_close_series(session, asset.id, limit=2) == [4.0, 5.0]


def test_mock_provider_bars_round_trip_through_validation_and_storage(
    session: Session, asset: models.Asset
) -> None:
    """End-to-end Phase 14 path: provider -> validation -> PostgreSQL."""
    provider = MockProvider()
    bars = provider.get_historical_prices("RELIANCE", dt.date(2024, 1, 1), dt.date(2024, 3, 1))

    report = validate_price_bars(bars, "RELIANCE", "1d", "mock")
    assert report.is_clean  # the mock walk must produce OHLC-consistent bars

    result = upsert_price_bars(session, asset.id, report.valid_bars)
    session.commit()

    assert result.inserted == len(bars)


def test_weekly_and_monthly_mock_bars_are_consistent_with_daily() -> None:
    provider = MockProvider()
    start, end = dt.date(2024, 1, 1), dt.date(2024, 3, 31)

    daily = provider.get_historical_prices("RELIANCE", start, end, Interval.DAILY)
    weekly = provider.get_historical_prices("RELIANCE", start, end, Interval.WEEKLY)
    monthly = provider.get_historical_prices("RELIANCE", start, end, Interval.MONTHLY)

    assert len(monthly) < len(weekly) < len(daily)
    assert all(bar.interval == "1wk" for bar in weekly)
    assert all(bar.high >= bar.low for bar in monthly)
    # A monthly bar must span its daily constituents.
    assert max(b.high for b in daily) == pytest.approx(max(b.high for b in monthly))


def test_validation_errors_are_persisted(session: Session, asset: models.Asset) -> None:
    corrupt = PriceBar(
        ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        open=100.0,
        high=90.0,
        low=95.0,
        close=104.0,
        volume=10,
        interval="1d",
        source="yahoo",
    )
    report = validate_price_bars([corrupt], "RELIANCE", "1d", "yahoo")

    written = save_validation_report(session, report, asset_id=asset.id)
    session.commit()

    assert written == 1
    stored = get_recent_validation_errors(session, ticker="RELIANCE")
    assert stored[0].code == "high_below_low"
    assert stored[0].severity == "error"
    assert stored[0].asset_id == asset.id
