from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.learning.engine import LearningEngine, period_bounds
from brain.learning.metrics import (
    NON_DIRECTIONAL_SIGNALS,
    forward_return,
    research_outcomes,
    signal_accuracy,
    strategy_performance,
    thesis_accuracy,
)
from brain.learning.schemas import MIN_SAMPLE_SIZE, AccuracyBlock, ReviewKind
from data.ingestion.schemas import PriceBar
from data.storage.learning_repository import get_learning_reviews, record_thesis_review
from data.storage.price_repository import upsert_price_bars
from models.base import Base
from tests.fakes import FakeKnowledgeStore

# A February review generated in March.
NOW = dt.datetime(2026, 3, 5, 12, 0, tzinfo=dt.UTC)
PERIOD_START = dt.date(2026, 2, 1)
PERIOD_END = dt.date(2026, 2, 28)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _asset(session: Session, ticker: str = "RELIANCE") -> models.Asset:
    asset = models.Asset(ticker=ticker, exchange="NSE", asset_type="equity", name=ticker)
    session.add(asset)
    session.flush()
    return asset


def _prices(session: Session, asset: models.Asset, series: list[tuple[dt.date, float]]) -> None:
    upsert_price_bars(
        session,
        asset.id,
        [
            PriceBar(
                ts=dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=100,
                interval="1d",
                source="test",
            )
            for day, close in series
        ],
    )
    session.flush()


def _signal(
    session: Session, asset: models.Asset, category: str, when: dt.datetime
) -> models.Signal:
    signal = models.Signal(
        asset_id=asset.id,
        signal_type="rule",
        category=category,
        confidence=0.7,
        reasoning="r",
        evidence=[{"kind": "quant", "detail": "d", "stance": "supports"}],
        value={},
        source="brain.signals.engine",
        status="active",
        generated_at=when,
    )
    session.add(signal)
    session.flush()
    return signal


# -- period boundaries --------------------------------------------------------


def test_monthly_period_is_the_last_completed_month() -> None:
    start, end = period_bounds(ReviewKind.MONTHLY, dt.date(2026, 3, 5))

    assert (start, end) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))


def test_quarterly_period_is_the_last_completed_quarter() -> None:
    start, end = period_bounds(ReviewKind.QUARTERLY, dt.date(2026, 5, 10))

    assert (start, end) == (dt.date(2026, 1, 1), dt.date(2026, 3, 31))


def test_annual_period_is_the_previous_year() -> None:
    start, end = period_bounds(ReviewKind.ANNUAL, dt.date(2026, 5, 10))

    assert (start, end) == (dt.date(2025, 1, 1), dt.date(2025, 12, 31))


# -- forward returns ----------------------------------------------------------


def test_forward_return_measures_from_the_anchor(session: Session) -> None:
    asset = _asset(session)
    _prices(
        session,
        asset,
        [(dt.date(2026, 2, 1), 100.0), (dt.date(2026, 2, 20), 120.0)],
    )

    move = forward_return(
        session, asset.id, dt.datetime(2026, 2, 1, tzinfo=dt.UTC), horizon_days=30
    )

    assert move == pytest.approx(0.2)


def test_forward_return_is_none_when_the_horizon_has_no_data(session: Session) -> None:
    """Unresolved is not zero -- 'not known yet' must not read as 'flat'."""
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 1), 100.0)])

    assert (
        forward_return(
            session, asset.id, dt.datetime(2026, 2, 1, tzinfo=dt.UTC), horizon_days=30
        )
        is None
    )


# -- accuracy block semantics -------------------------------------------------


def test_accuracy_is_none_when_nothing_resolved() -> None:
    block = AccuracyBlock(label="x", unresolved=5)

    assert block.accuracy is None
    assert block.caveat == "No resolved outcomes yet."


def test_small_samples_are_never_significant() -> None:
    block = AccuracyBlock(label="x", correct=3, incorrect=0)

    assert block.accuracy == 1.0
    assert not block.is_significant
    assert "too small" in (block.caveat or "")


def test_large_samples_lose_the_caveat() -> None:
    block = AccuracyBlock(label="x", correct=MIN_SAMPLE_SIZE, incorrect=0)

    assert block.is_significant
    assert block.caveat is None


# -- thesis accuracy ----------------------------------------------------------


def test_thesis_accuracy_counts_current_assessments(session: Session) -> None:
    asset = _asset(session)
    for assessment in (
        "THESIS_INTACT",
        "THESIS_STRENGTHENED",
        "THESIS_WEAKENED",
        "THESIS_INVALIDATED",
    ):
        session.add(
            models.Thesis(
                asset_id=asset.id, title=assessment, status="active",
                current_assessment=assessment,
            )
        )
    session.flush()

    result = thesis_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.total_theses == 4
    assert result.invalidated == 1
    assert result.invalidation_rate == 0.25


def test_time_to_invalidation_uses_the_first_invalidating_review(
    session: Session,
) -> None:
    """A later re-review must not restart the clock."""
    asset = _asset(session)
    thesis = models.Thesis(
        asset_id=asset.id, title="t", status="active", current_assessment="THESIS_INVALIDATED"
    )
    session.add(thesis)
    session.flush()
    thesis.created_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    session.flush()

    record_thesis_review(
        session, thesis.id, asset.id, "THESIS_INTACT", "THESIS_INVALIDATED",
        reviewed_at=dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
    )
    record_thesis_review(
        session, thesis.id, asset.id, "THESIS_INVALIDATED", "THESIS_INVALIDATED",
        reviewed_at=dt.datetime(2026, 2, 28, tzinfo=dt.UTC),
    )
    session.flush()

    result = thesis_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.days_to_invalidation == [30]
    assert result.median_days_to_invalidation == 30.0


def test_no_invalidations_reports_none_not_zero(session: Session) -> None:
    session.add(
        models.Thesis(title="t", status="active", current_assessment="THESIS_INTACT")
    )
    session.flush()

    result = thesis_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.median_days_to_invalidation is None


# -- signal accuracy ----------------------------------------------------------


def test_accumulate_is_correct_when_price_rose(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 130.0)])
    _signal(session, asset, "ACCUMULATE", dt.datetime(2026, 2, 5, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.by_category["ACCUMULATE"].correct == 1
    assert result.overall.accuracy == 1.0


def test_accumulate_is_a_false_positive_when_price_fell(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 80.0)])
    _signal(session, asset, "ACCUMULATE", dt.datetime(2026, 2, 5, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.by_category["ACCUMULATE"].incorrect == 1
    assert result.false_positives == 1


def test_exit_review_is_correct_when_price_fell(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 70.0)])
    _signal(session, asset, "EXIT_REVIEW", dt.datetime(2026, 2, 5, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.by_category["EXIT_REVIEW"].correct == 1


@pytest.mark.parametrize("category", NON_DIRECTIONAL_SIGNALS)
def test_non_directional_signals_are_excluded_not_scored(
    session: Session, category: str
) -> None:
    """Scoring these against a direction they never claimed would be unfair."""
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 70.0)])
    _signal(session, asset, category, dt.datetime(2026, 2, 5, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert category not in result.by_category
    assert result.overall.sample_size == 0
    assert category in result.excluded_categories


def test_unresolved_signals_are_counted_separately(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 25), 100.0)])  # nothing after
    _signal(session, asset, "ACCUMULATE", dt.datetime(2026, 2, 25, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.overall.unresolved == 1
    assert result.overall.sample_size == 0
    assert result.overall.accuracy is None


def test_an_unwarned_crash_counts_as_a_false_negative(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 1), 100.0), (dt.date(2026, 2, 20), 50.0)])

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.false_negatives == 1


def test_a_warned_crash_is_not_a_false_negative(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 1), 100.0), (dt.date(2026, 2, 20), 50.0)])
    _signal(session, asset, "EXIT_REVIEW", dt.datetime(2026, 2, 1, tzinfo=dt.UTC))

    result = signal_accuracy(session, PERIOD_START, PERIOD_END)

    assert result.false_negatives == 0


# -- research outcomes --------------------------------------------------------


def test_research_outcomes_are_explicitly_not_an_accuracy_score(
    session: Session,
) -> None:
    """Rule 4: research states no direction, so it cannot be graded on one."""
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 110.0)])
    document = models.ResearchDocument(
        asset_id=asset.id, title="r", summary="s", source="claude"
    )
    session.add(document)
    session.flush()
    document.created_at = dt.datetime(2026, 2, 5, tzinfo=dt.UTC)
    session.flush()

    result = research_outcomes(session, PERIOD_START, PERIOD_END)

    assert result.resolved == 1
    assert result.mean_forward_return == pytest.approx(0.1)
    assert result.to_dict()["is_accuracy_score"] is False
    assert "falsifiable" in result.why_not_accuracy


# -- strategy performance -----------------------------------------------------


def _closed_trade(
    session: Session, asset: models.Asset, r: float | None, regime: str = "BULLISH"
) -> models.Trade:
    trade = models.Trade(
        asset_id=asset.id,
        direction="long",
        timeframe="1d",
        entry_price=100,
        position_size=10,
        status="closed",
        result="win" if (r or 0) > 0 else "loss",
        r_multiple=r,
        market_regime=regime,
        opened_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
        closed_at=dt.datetime(2026, 2, 15, tzinfo=dt.UTC),
    )
    session.add(trade)
    session.flush()
    return trade


def test_strategy_performance_groups_by_regime_sector_and_cap(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.Company(asset_id=asset.id, sector="Energy", market_cap=5_000_000_000)
    )
    session.flush()
    _closed_trade(session, asset, 2.0)
    _closed_trade(session, asset, -1.0)

    result = strategy_performance(session, PERIOD_START, PERIOD_END)

    assert result.scored_trades == 2
    assert result.by_regime[0].label == "BULLISH"
    assert result.by_sector[0].label == "Energy"
    assert result.by_market_cap[0].label == "mid (2B-10B)"
    assert result.by_regime[0].win_rate == 0.5


def test_trades_without_an_r_multiple_are_excluded_and_counted(session: Session) -> None:
    """They can't be scored without inventing the risk that was never set."""
    asset = _asset(session)
    _closed_trade(session, asset, 2.0)
    _closed_trade(session, asset, None)

    result = strategy_performance(session, PERIOD_START, PERIOD_END)

    assert result.scored_trades == 1
    assert result.trades_without_r_multiple == 1


def test_small_groups_carry_a_sample_size_warning(session: Session) -> None:
    asset = _asset(session)
    _closed_trade(session, asset, 1.0)

    result = strategy_performance(session, PERIOD_START, PERIOD_END)

    assert not result.by_regime[0].is_significant
    assert "too small" in (result.by_regime[0].caveat or "")


# -- engine -------------------------------------------------------------------


def test_report_renders_with_caveats_and_disclaimer(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 130.0)])
    _signal(session, asset, "ACCUMULATE", dt.datetime(2026, 2, 5, tzinfo=dt.UTC))
    _closed_trade(session, asset, 1.5)

    report = LearningEngine().build_report(session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW)
    markdown = LearningEngine().render_markdown(report)

    assert "Past results do not predict future results" in markdown
    assert "Not an accuracy score" in markdown
    assert "⚠" in markdown  # small samples flagged inline
    assert "Excluded (no directional claim)" in markdown


def test_run_persists_to_postgres_and_obsidian(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [(dt.date(2026, 2, 5), 100.0), (dt.date(2026, 2, 25), 130.0)])
    _signal(session, asset, "ACCUMULATE", dt.datetime(2026, 2, 5, tzinfo=dt.UTC))
    store = FakeKnowledgeStore()

    report = LearningEngine().run(session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW,
                                  knowledge_store=store)
    session.commit()

    reviews = get_learning_reviews(session)
    assert len(reviews) == 1
    assert reviews[0].kind == "monthly"
    assert reviews[0].period_start == PERIOD_START
    assert reviews[0].metrics["signal_accuracy"]["overall"]["correct"] == 1
    note_path = reviews[0].obsidian_note_path
    assert note_path is not None and note_path in store.notes
    assert report.period_end == PERIOD_END


def test_regenerating_a_period_updates_rather_than_duplicates(session: Session) -> None:
    engine = LearningEngine()
    engine.run(session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW)
    engine.run(session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW)
    session.commit()

    assert len(get_learning_reviews(session)) == 1


def test_run_works_without_obsidian(session: Session) -> None:
    """A missing knowledge store must not lose the PostgreSQL record."""
    LearningEngine().run(session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW)
    session.commit()

    reviews = get_learning_reviews(session)
    assert len(reviews) == 1
    assert reviews[0].obsidian_note_path is None


def test_empty_history_produces_an_honest_empty_report(session: Session) -> None:
    report = LearningEngine().build_report(
        session, ReviewKind.MONTHLY, as_of=NOW.date(), now=NOW
    )
    markdown = LearningEngine().render_markdown(report)

    assert report.thesis.total_theses == 0
    assert report.signals.overall.accuracy is None
    assert "No resolved outcomes yet." in markdown
    assert "no invalidations recorded yet" in markdown
