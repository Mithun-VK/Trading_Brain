from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.review.review_agent import TradeJournalReviewAgent
from models.base import Base
from tests.fakes import FakeKnowledgeStore, FakeLLMProvider

_PATTERN_RESPONSE = {
    "patterns": ["Wins cluster in bullish regimes"],
    "repeated_mistakes": ["Frequently exits winners early"],
    "rule_violations": [],
    "lessons": ["Let winners run to target in trending regimes"],
    "confidence": 0.4,
}


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_trade(
    asset_id: int, strategy_id: int | None, r_multiple: float, regime: str, status: str = "closed"
) -> models.Trade:
    return models.Trade(
        asset_id=asset_id,
        strategy_id=strategy_id,
        direction="long",
        timeframe="1d",
        entry_price=100,
        stop_price=95,
        risk_amount=500,
        position_size=100,
        status=status,
        result="win" if r_multiple > 0 else "loss",
        r_multiple=r_multiple,
        market_regime=regime,
        opened_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )


def _seed_trades(session: Session) -> list[models.Trade]:
    asset = models.Asset(ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance")
    strategy = models.Strategy(name="breakout", rules={})
    session.add_all([asset, strategy])
    session.flush()

    trades = [
        _make_trade(asset.id, strategy.id, 2.0, "BULLISH"),
        _make_trade(asset.id, strategy.id, -1.0, "BULLISH"),
        _make_trade(asset.id, strategy.id, 1.0, "SIDEWAYS"),
        _make_trade(asset.id, None, 0.5, "BULLISH", status="open"),  # excluded: still open
    ]
    session.add_all(trades)
    session.commit()
    return trades


def test_review_computes_deterministic_overall_stats(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    agent = TradeJournalReviewAgent(session, llm, FakeKnowledgeStore())

    review = agent.review(trades)

    assert review.overall.trade_count == 3
    assert review.overall.win_rate == pytest.approx(2 / 3)
    assert review.overall.profit_factor == pytest.approx(3.0)
    assert review.overall.expectancy_r == pytest.approx(2 / 3)


def test_review_flags_small_sample_size(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    agent = TradeJournalReviewAgent(session, llm, FakeKnowledgeStore())

    review = agent.review(trades)

    assert review.overall.sample_size_warning is not None
    assert "n=3" in review.overall.sample_size_warning


def test_review_groups_by_strategy_and_regime(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    agent = TradeJournalReviewAgent(session, llm, FakeKnowledgeStore())

    review = agent.review(trades)

    strategy_labels = {g.label for g in review.by_strategy}
    regime_labels = {g.label for g in review.by_regime}
    assert strategy_labels == {"breakout"}
    assert regime_labels == {"BULLISH", "SIDEWAYS"}


def test_review_includes_claude_pattern_output(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    agent = TradeJournalReviewAgent(session, llm, FakeKnowledgeStore())

    review = agent.review(trades)

    assert review.patterns == _PATTERN_RESPONSE["patterns"]
    assert review.confidence == 0.4


def test_render_markdown_includes_warning_and_disclaimer(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    agent = TradeJournalReviewAgent(session, llm, FakeKnowledgeStore())

    review = agent.review(trades)
    markdown = agent.render_markdown(review)

    assert "sample-size warning" in markdown.lower() or "significant" in markdown.lower()
    assert "Wins cluster in bullish regimes" in markdown


def test_publish_writes_note(session: Session) -> None:
    trades = _seed_trades(session)
    llm = FakeLLMProvider(extract_response=_PATTERN_RESPONSE)
    knowledge_store = FakeKnowledgeStore()
    agent = TradeJournalReviewAgent(session, llm, knowledge_store)

    review = agent.review(trades)
    path = agent.publish(review)

    assert path.startswith("09 Reviews/")
    assert path in knowledge_store.notes
