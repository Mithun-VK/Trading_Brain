from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.market.context_assembler import ContextAssembler
from data.ingestion.mock_provider import MockProvider
from models.base import Base
from tests.fakes import FakeKnowledgeStore


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_build_includes_quant_summary_even_with_no_db_rows(session: Session) -> None:
    assembler = ContextAssembler(FakeKnowledgeStore(), session, MockProvider())

    bundle = assembler.build(
        "RELIANCE", include_company=False, include_thesis=False, include_recent_trades=False
    )

    assert bundle.quant_summary["source"] == "mock"
    assert "last_close" in bundle.quant_summary
    assert bundle.thesis_summary is None
    assert bundle.recent_trades == []


def test_build_includes_company_and_sector_notes(session: Session) -> None:
    knowledge_store = FakeKnowledgeStore(
        {
            "02 Companies/India/RELIANCE.md": "# RELIANCE\nsector: Energy",
            "03 Sectors/Energy.md": "# Energy sector overview",
        }
    )
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    session.add(models.Company(asset_id=asset.id, sector="Energy"))
    session.commit()

    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    bundle = assembler.build("RELIANCE", include_thesis=False, include_recent_trades=False)

    assert any("RELIANCE" in r.path for r in bundle.company_notes)
    assert any("Energy" in r.path for r in bundle.sector_notes)


def test_build_includes_active_thesis(session: Session) -> None:
    knowledge_store = FakeKnowledgeStore({"06 Investment Theses/RELIANCE.md": "Thesis body text"})
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    session.add(
        models.Thesis(
            asset_id=asset.id,
            title="RELIANCE refining upcycle",
            status="active",
            current_assessment="THESIS_INTACT",
            obsidian_note_path="06 Investment Theses/RELIANCE.md",
        )
    )
    session.commit()

    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    bundle = assembler.build("RELIANCE", include_company=False, include_recent_trades=False)

    assert bundle.thesis_summary is not None
    assert bundle.thesis_summary["current_assessment"] == "THESIS_INTACT"
    assert bundle.thesis_note is not None
    assert bundle.thesis_note.content == "Thesis body text"


def test_build_includes_recent_trades(session: Session) -> None:
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    session.add(
        models.Trade(
            asset_id=asset.id,
            direction="long",
            timeframe="1d",
            entry_price=100,
            stop_price=95,
            risk_amount=500,
            position_size=100,
            status="closed",
            result="win",
            r_multiple=2.0,
            opened_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )
    )
    session.commit()

    assembler = ContextAssembler(FakeKnowledgeStore(), session, MockProvider())
    bundle = assembler.build("RELIANCE", include_company=False, include_thesis=False)

    assert len(bundle.recent_trades) == 1
    assert bundle.recent_trades[0]["result"] == "win"
    assert bundle.recent_trades[0]["r_multiple"] == 2.0


def test_build_includes_latest_market_regime(session: Session) -> None:
    session.add(
        models.MarketRegimeObservation(
            observed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            regime="BULLISH",
            volatility_regime="LOW_VOLATILITY",
            risk_regime="RISK_ON",
        )
    )
    session.add(
        models.MarketRegimeObservation(
            observed_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            regime="SIDEWAYS",
            volatility_regime="HIGH_VOLATILITY",
            risk_regime="UNKNOWN",
        )
    )
    session.commit()

    assembler = ContextAssembler(FakeKnowledgeStore(), session, MockProvider())
    bundle = assembler.build(
        "RELIANCE", include_company=False, include_thesis=False, include_recent_trades=False
    )

    assert bundle.market_regime == {
        "trend_regime": "SIDEWAYS",
        "volatility_regime": "HIGH_VOLATILITY",
        "risk_regime": "UNKNOWN",
    }


def test_to_prompt_context_truncates_thesis_note(session: Session) -> None:
    long_body = "x" * 5000
    knowledge_store = FakeKnowledgeStore({"06 Investment Theses/T.md": long_body})
    asset = models.Asset(ticker="TCS", exchange="NSE", asset_type="equity", name="TCS")
    session.add(asset)
    session.flush()
    session.add(
        models.Thesis(
            asset_id=asset.id,
            title="TCS thesis",
            status="active",
            obsidian_note_path="06 Investment Theses/T.md",
        )
    )
    session.commit()

    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    bundle = assembler.build("TCS", include_company=False, include_recent_trades=False)
    prompt = bundle.to_prompt_context()

    assert len(prompt) < len(long_body) + 1000
