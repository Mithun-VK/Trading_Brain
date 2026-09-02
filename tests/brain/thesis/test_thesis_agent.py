from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.market.context_assembler import ContextAssembler
from brain.thesis.schemas import ThesisAssessment
from brain.thesis.thesis_agent import ThesisAgent
from data.ingestion.mock_provider import MockProvider
from models.base import Base
from tests.fakes import FakeKnowledgeStore, FakeLLMProvider

_REVIEW_RESPONSE = {
    "assessment": "THESIS_WEAKENED",
    "reasoning": "Refining margins compressed more than expected.",
    "supporting_evidence": ["Q3 margins held above guidance"],
    "contradicting_evidence": ["Petrochemical segment missed for third straight quarter"],
    "changed_assumptions": ["Assumed petchem recovery by H2 -- now delayed"],
    "invalidation_conditions_triggered": [],
    "confidence": 0.55,
}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_asset_and_thesis(
    session: Session, note_path: str | None = "06 Investment Theses/T.md"
) -> tuple[models.Asset, models.Thesis]:
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    session.add(asset)
    session.flush()
    thesis = models.Thesis(
        asset_id=asset.id,
        title="RELIANCE refining upcycle",
        status="active",
        current_assessment="THESIS_INTACT",
        obsidian_note_path=note_path,
    )
    session.add(thesis)
    session.commit()
    return asset, thesis


def test_review_returns_structured_assessment(session: Session) -> None:
    asset, thesis = _seed_asset_and_thesis(session)
    knowledge_store = FakeKnowledgeStore({thesis.obsidian_note_path: "## Historical Changes\n"})
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    review = agent.review(thesis, asset)

    assert review.assessment is ThesisAssessment.THESIS_WEAKENED
    assert review.previous_assessment == "THESIS_INTACT"
    assert review.thesis_id == thesis.id


def test_apply_appends_audit_entry_without_erasing_existing_content(session: Session) -> None:
    asset, thesis = _seed_asset_and_thesis(session)
    original_content = (
        "# Thesis\n\n## Thesis Statement\nBullish on refining.\n\n## Historical Changes\n"
    )
    knowledge_store = FakeKnowledgeStore({thesis.obsidian_note_path: original_content})
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    review = agent.review(thesis, asset)
    agent.apply(thesis, review)

    updated_content = knowledge_store.notes[thesis.obsidian_note_path]
    assert original_content in updated_content
    assert "THESIS_INTACT -> THESIS_WEAKENED" in updated_content
    assert "Refining margins compressed" in updated_content


def test_apply_updates_tracked_assessment_and_review_timestamp(session: Session) -> None:
    asset, thesis = _seed_asset_and_thesis(session)
    knowledge_store = FakeKnowledgeStore({thesis.obsidian_note_path: "## Historical Changes\n"})
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    review = agent.review(thesis, asset)
    agent.apply(thesis, review)

    assert thesis.current_assessment == "THESIS_WEAKENED"
    assert thesis.last_reviewed_at is not None


def test_review_and_apply_never_silently_skips_the_audit_trail(session: Session) -> None:
    asset, thesis = _seed_asset_and_thesis(session)
    knowledge_store = FakeKnowledgeStore({thesis.obsidian_note_path: "## Historical Changes\n"})
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    before = knowledge_store.notes[thesis.obsidian_note_path]
    agent.review_and_apply(thesis, asset)
    after = knowledge_store.notes[thesis.obsidian_note_path]

    assert after != before
    assert len(after) > len(before)


def test_apply_handles_thesis_without_note_path(session: Session) -> None:
    asset, thesis = _seed_asset_and_thesis(session, note_path=None)
    knowledge_store = FakeKnowledgeStore()
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    review = agent.review(thesis, asset)
    agent.apply(thesis, review)

    assert thesis.current_assessment == "THESIS_WEAKENED"


def test_audit_entry_lands_inside_the_history_section_not_at_the_end(
    session: Session,
) -> None:
    """Rule 9: placement must not depend on Historical Changes being last."""
    asset, thesis = _seed_asset_and_thesis(session)
    note = (
        "# Thesis\n\n"
        "## Historical Changes\n\n"
        "## Invalidation Conditions\n\nMargins below 8%.\n"
    )
    knowledge_store = FakeKnowledgeStore({thesis.obsidian_note_path: note})
    llm = FakeLLMProvider(extract_response=_REVIEW_RESPONSE)
    assembler = ContextAssembler(knowledge_store, session, MockProvider())
    agent = ThesisAgent(assembler, llm, knowledge_store, session)

    agent.review_and_apply(thesis, asset)

    updated = knowledge_store.notes[thesis.obsidian_note_path]
    history_at = updated.index("## Historical Changes")
    invalidation_at = updated.index("## Invalidation Conditions")
    entry_at = updated.index("THESIS_INTACT -> THESIS_WEAKENED")

    assert history_at < entry_at < invalidation_at
    # The human-authored section below it must be untouched.
    assert "Margins below 8%." in updated
