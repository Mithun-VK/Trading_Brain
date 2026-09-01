"""Model-layer tests. Uses an in-memory SQLite engine so no PostgreSQL
instance is required to validate the ORM schema is internally consistent
(FKs resolve, tables create, round-trip inserts work).
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from models.base import Base


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_all_tables_created(engine) -> None:
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "assets",
        "companies",
        "prices",
        "financial_metrics",
        "market_events",
        "market_regimes",
        "trades",
        "positions",
        "strategies",
        "signals",
        "research_documents",
        "theses",
    }
    assert expected.issubset(table_names)


def test_asset_company_relationship(engine) -> None:
    with Session(engine) as session:
        asset = models.Asset(
            ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance Industries"
        )
        session.add(asset)
        session.flush()

        company = models.Company(asset_id=asset.id, sector="Energy", industry="Refining")
        session.add(company)
        session.commit()

        fetched = session.get(models.Asset, asset.id)
        assert fetched is not None
        assert fetched.company is not None
        assert fetched.company.sector == "Energy"


def test_trade_round_trip(engine) -> None:
    with Session(engine) as session:
        asset = models.Asset(ticker="TCS", exchange="NSE", asset_type="equity", name="TCS")
        session.add(asset)
        session.flush()

        trade = models.Trade(
            asset_id=asset.id,
            direction="long",
            timeframe="1d",
            entry_price=100,
            stop_price=95,
            target_price=120,
            risk_amount=500,
            position_size=100,
            opened_at=dt.datetime.now(dt.UTC),
        )
        session.add(trade)
        session.commit()

        fetched = session.get(models.Trade, trade.id)
        assert fetched is not None
        assert fetched.status == "open"


def test_price_uniqueness_constraint(engine) -> None:
    with Session(engine) as session:
        asset = models.Asset(ticker="INFY", exchange="NSE", asset_type="equity", name="Infosys")
        session.add(asset)
        session.flush()

        ts = dt.datetime.now(dt.UTC)
        session.add(
            models.Price(
                asset_id=asset.id,
                ts=ts,
                interval="1d",
                open=1,
                high=2,
                low=1,
                close=1.5,
                volume=1000,
                source="mock",
            )
        )
        session.commit()

        session.add(
            models.Price(
                asset_id=asset.id,
                ts=ts,
                interval="1d",
                open=1,
                high=2,
                low=1,
                close=1.5,
                volume=1000,
                source="mock",
            )
        )
        with pytest.raises(Exception):  # noqa: B017 -- IntegrityError, backend-specific
            session.commit()
