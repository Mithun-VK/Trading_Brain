from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.market.context_assembler import ContextAssembler
from brain.research.research_agent import ResearchAgent
from data.ingestion.mock_provider import MockProvider
from data.storage.research_repository import save_research_document
from models.base import Base
from tests.fakes import FakeKnowledgeStore, FakeLLMProvider

_EXTRACT_RESPONSE = {
    "summary": "Reliance shows steady refining margins.",
    "positive_factors": ["Strong refining margins"],
    "negative_factors": ["Petrochemical weakness"],
    "contradictions": ["Bull note says demand is soft; bear note says it's strong"],
    "risks": ["Crude price volatility"],
    "catalysts": ["New energy segment ramp-up"],
    "confidence": 0.65,
}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _agent(
    session: Session, knowledge_store: FakeKnowledgeStore, llm: FakeLLMProvider
) -> ResearchAgent:
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    return ResearchAgent(assembler, llm, knowledge_store, session)


def test_research_returns_structured_analysis(session: Session) -> None:
    llm = FakeLLMProvider(extract_response=_EXTRACT_RESPONSE)
    agent = _agent(session, FakeKnowledgeStore(), llm)

    analysis = agent.research("RELIANCE")

    assert analysis.ticker == "RELIANCE"
    assert analysis.confidence == 0.65
    assert analysis.positive_factors == ["Strong refining margins"]
    assert llm.calls[0][0] == "extract"


def test_research_includes_previous_summary_in_prompt(session: Session) -> None:
    from brain.research.schemas import ResearchAnalysis

    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    session.commit()

    prior_analysis = ResearchAnalysis(
        ticker="RELIANCE", summary="Old thesis was bullish", confidence=0.5
    )
    save_research_document(session, prior_analysis, note_path="08 Research/old.md", asset=asset)
    session.commit()

    llm = FakeLLMProvider(extract_response=_EXTRACT_RESPONSE)
    agent = _agent(session, FakeKnowledgeStore(), llm)

    agent.research("RELIANCE", asset=asset)

    prompt_text = llm.calls[0][1][0]
    assert "Old thesis was bullish" in prompt_text


def test_render_markdown_includes_disclaimer_and_sections() -> None:
    from brain.research.schemas import ResearchAnalysis

    llm = FakeLLMProvider()
    agent = _agent(Session(create_engine("sqlite:///:memory:")), FakeKnowledgeStore(), llm)
    analysis = ResearchAnalysis(ticker="RELIANCE", source_notes=["a.md"], **_EXTRACT_RESPONSE)

    markdown = agent.render_markdown(analysis)

    assert "Not a guaranteed prediction or financial advice" in markdown
    assert "## Summary" in markdown
    assert "## Contradictions" in markdown
    assert "[[a.md]]" in markdown


def test_publish_writes_note_and_persists_row(session: Session) -> None:
    knowledge_store = FakeKnowledgeStore()
    llm = FakeLLMProvider(extract_response=_EXTRACT_RESPONSE)
    agent = _agent(session, knowledge_store, llm)

    analysis = agent.research("RELIANCE")
    path = agent.publish(analysis)
    session.commit()

    assert path in knowledge_store.notes
    assert "## Summary" in knowledge_store.notes[path]

    saved = session.query(models.ResearchDocument).one()
    assert saved.obsidian_note_path == path
    assert saved.source == "claude"
