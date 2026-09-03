from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from apps.api.ai_dependencies import (
    get_journal_llm,
    get_queue_research_llm,
    get_research_llm,
    get_thesis_llm,
)
from apps.api.dependencies import (
    get_knowledge_store,
    get_market_data,
    get_session,
)
from apps.api.main import create_app
from data.ingestion.mock_provider import MockProvider
from models.base import Base
from tests.fakes import FakeKnowledgeStore, FakeLLMProvider

_DEFAULT_EXTRACT_RESPONSE = {
    "summary": "test summary",
    "positive_factors": [],
    "negative_factors": [],
    "contradictions": [],
    "risks": [],
    "catalysts": [],
    "confidence": 0.5,
    "assessment": "THESIS_INTACT",
    "reasoning": "no material change",
    "supporting_evidence": [],
    "contradicting_evidence": [],
    "changed_assumptions": [],
    "invalidation_conditions_triggered": [],
    "patterns": [],
    "repeated_mistakes": [],
    "rule_violations": [],
    "lessons": [],
}


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def db_session(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def knowledge_store() -> FakeKnowledgeStore:
    return FakeKnowledgeStore()


@pytest.fixture
def llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider(extract_response=dict(_DEFAULT_EXTRACT_RESPONSE))


@pytest.fixture
def client(session_factory, knowledge_store, llm_provider) -> TestClient:
    app = create_app()

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_knowledge_store] = lambda: knowledge_store
    app.dependency_overrides[get_market_data] = lambda: MockProvider()
    # One override per AI-capable route. The task type is fixed by the
    # endpoint rather than chosen by the caller, so each route has its own
    # dependency and each needs overriding here.
    for ai_dependency in (
        get_research_llm,
        get_queue_research_llm,
        get_thesis_llm,
        get_journal_llm,
    ):
        app.dependency_overrides[ai_dependency] = lambda: llm_provider

    return TestClient(app)


@pytest.fixture
def seeded_asset(db_session: Session) -> models.Asset:
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    db_session.add(asset)
    db_session.flush()
    db_session.add(models.Company(asset_id=asset.id, sector="Energy", industry="Refining"))
    db_session.commit()
    return asset


@pytest.fixture
def seeded_thesis(db_session: Session, seeded_asset: models.Asset) -> models.Thesis:
    thesis = models.Thesis(
        asset_id=seeded_asset.id,
        title="RELIANCE refining upcycle",
        status="active",
        current_assessment="THESIS_INTACT",
        obsidian_note_path="06 Investment Theses/RELIANCE.md",
    )
    db_session.add(thesis)
    db_session.commit()
    return thesis


@pytest.fixture
def seeded_trade(db_session: Session, seeded_asset: models.Asset) -> models.Trade:
    trade = models.Trade(
        asset_id=seeded_asset.id,
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
    db_session.add(trade)
    db_session.commit()
    return trade
