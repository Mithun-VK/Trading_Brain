from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.research.change_detection import (
    ChangeDetectionConfig,
    ChangeDetector,
    ChangeType,
    detect_regime_change,
)
from brain.research.intelligence import ResearchIntelligenceEngine
from brain.research.priority import PriorityWeights, ResearchPriorityScorer
from data.ingestion.schemas import PriceBar
from data.storage.price_repository import upsert_price_bars
from data.storage.research_queue_repository import (
    STATUS_PENDING,
    dismiss,
    get_queue,
    mark_done,
    next_entry,
)
from data.storage.watchlist_repository import add_item, create_watchlist
from models.base import Base

NOW = dt.datetime(2026, 2, 1, 12, 0, tzinfo=dt.UTC)


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


def _add_closes(session: Session, asset: models.Asset, closes: list[float]) -> None:
    """Store `closes` as consecutive daily bars ending the day before NOW."""
    bars = []
    for offset, close in enumerate(reversed(closes)):
        day = NOW - dt.timedelta(days=offset + 1)
        bars.append(
            PriceBar(
                ts=day.replace(hour=0, minute=0, second=0, microsecond=0),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1000,
                interval="1d",
                source="test",
            )
        )
    upsert_price_bars(session, asset.id, bars)
    session.flush()


def _research_doc(session: Session, asset: models.Asset, days_ago: int) -> None:
    doc = models.ResearchDocument(
        asset_id=asset.id, title="prior", summary="prior", source="claude"
    )
    session.add(doc)
    session.flush()
    doc.created_at = NOW - dt.timedelta(days=days_ago)
    session.flush()


# -- change detection ---------------------------------------------------------


def test_price_shock_is_detected(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 108.0])  # +8% in a day

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    shock = next(c for c in changes if c.change_type is ChangeType.PRICE_SHOCK)
    assert shock.detail["direction"] == "up"
    assert shock.magnitude == pytest.approx(0.8, abs=0.01)


def test_quiet_market_produces_no_price_change(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 100.5])
    _research_doc(session, asset, days_ago=1)

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    assert [c for c in changes if c.change_type is ChangeType.PRICE_SHOCK] == []


def test_price_shock_magnitude_saturates_at_one(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 200.0])

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    shock = next(c for c in changes if c.change_type is ChangeType.PRICE_SHOCK)
    assert shock.magnitude == 1.0


def test_large_move_over_the_window_is_detected(session: Session) -> None:
    asset = _asset(session)
    # A slow 20% grind up: no single-day shock, but a large cumulative move.
    closes = [100.0 * (1.009**i) for i in range(21)]
    _add_closes(session, asset, closes)

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    types = {c.change_type for c in changes}
    assert ChangeType.LARGE_MOVE in types
    assert ChangeType.PRICE_SHOCK not in types


def test_earnings_release_is_detected(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.MarketEvent(
            event_type="earnings",
            title="Q3 results",
            occurred_at=NOW - dt.timedelta(days=2),
            related_asset_id=asset.id,
            source="test",
        )
    )
    session.flush()

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    earnings = next(c for c in changes if c.change_type is ChangeType.EARNINGS_RELEASE)
    assert earnings.magnitude == 1.0


def test_old_earnings_are_ignored(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.MarketEvent(
            event_type="earnings",
            title="Old results",
            occurred_at=NOW - dt.timedelta(days=90),
            related_asset_id=asset.id,
            source="test",
        )
    )
    session.flush()

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    assert ChangeType.EARNINGS_RELEASE not in {c.change_type for c in changes}


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [("THESIS_INVALIDATED", 1.0), ("THESIS_WEAKENED", 0.7)],
)
def test_thesis_violation_is_detected(
    session: Session, assessment: str, expected: float
) -> None:
    asset = _asset(session)
    session.add(
        models.Thesis(
            asset_id=asset.id,
            title="t",
            status="active",
            current_assessment=assessment,
            last_reviewed_at=NOW,
        )
    )
    session.flush()

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    violation = next(c for c in changes if c.change_type is ChangeType.THESIS_VIOLATION)
    assert violation.magnitude == expected


def test_intact_but_unreviewed_thesis_is_flagged(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.Thesis(
            asset_id=asset.id,
            title="t",
            status="active",
            current_assessment="THESIS_INTACT",
            last_reviewed_at=NOW - dt.timedelta(days=200),
        )
    )
    session.flush()

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    violation = next(c for c in changes if c.change_type is ChangeType.THESIS_VIOLATION)
    assert violation.detail["reason"] == "thesis not reviewed recently"


def test_recently_reviewed_intact_thesis_is_not_flagged(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.Thesis(
            asset_id=asset.id,
            title="t",
            status="active",
            current_assessment="THESIS_INTACT",
            last_reviewed_at=NOW - dt.timedelta(days=2),
        )
    )
    session.flush()

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    assert ChangeType.THESIS_VIOLATION not in {c.change_type for c in changes}


def test_never_researched_asset_is_stale(session: Session) -> None:
    asset = _asset(session)

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    stale = next(c for c in changes if c.change_type is ChangeType.STALE_RESEARCH)
    assert stale.detail["reason"] == "never researched"


def test_recent_research_is_not_stale(session: Session) -> None:
    asset = _asset(session)
    _research_doc(session, asset, days_ago=3)

    changes = ChangeDetector().detect_for_asset(session, asset, NOW)

    assert ChangeType.STALE_RESEARCH not in {c.change_type for c in changes}


def test_thresholds_are_configurable(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 102.0])  # +2%

    lenient = ChangeDetector().detect_for_asset(session, asset, NOW)
    strict = ChangeDetector(ChangeDetectionConfig(price_shock_pct=0.01)).detect_for_asset(
        session, asset, NOW
    )

    assert ChangeType.PRICE_SHOCK not in {c.change_type for c in lenient}
    assert ChangeType.PRICE_SHOCK in {c.change_type for c in strict}


def _regime(session: Session, trend: str, when: dt.datetime) -> None:
    session.add(
        models.MarketRegimeObservation(
            observed_at=when,
            regime=trend,
            volatility_regime="LOW_VOLATILITY",
            risk_regime="RISK_ON",
        )
    )
    session.flush()


def test_regime_change_is_detected(session: Session) -> None:
    _regime(session, "BULLISH", NOW - dt.timedelta(days=2))
    _regime(session, "BEARISH", NOW)

    change = detect_regime_change(session, NOW)

    assert change is not None
    assert change.magnitude == 1.0
    assert change.detail["to"]["trend"] == "BEARISH"


def test_unchanged_regime_produces_nothing(session: Session) -> None:
    _regime(session, "BULLISH", NOW - dt.timedelta(days=2))
    _regime(session, "BULLISH", NOW)

    assert detect_regime_change(session, NOW) is None


def test_single_observation_cannot_be_a_change(session: Session) -> None:
    _regime(session, "BULLISH", NOW)

    assert detect_regime_change(session, NOW) is None


# -- priority scoring ---------------------------------------------------------


def test_score_is_bounded_and_explainable(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])
    change = next(
        c
        for c in ChangeDetector().detect_for_asset(session, asset, NOW)
        if c.change_type is ChangeType.PRICE_SHOCK
    )

    priority = ResearchPriorityScorer().score(session, change, NOW)

    assert 0.0 <= priority.score <= 1.0
    assert priority.reasons  # never an opaque ranking


def test_held_and_watched_assets_outrank_identical_unknown_ones(session: Session) -> None:
    tracked = _asset(session, "TRACKED")
    ignored = _asset(session, "IGNORED")
    for asset in (tracked, ignored):
        _add_closes(session, asset, [100.0, 110.0])

    watchlist = create_watchlist(session, "High Conviction")
    add_item(session, watchlist, tracked)
    portfolio = models.PaperPortfolio(
        name="Core", initial_cash=100_000, cash_balance=50_000
    )
    session.add(portfolio)
    session.flush()
    session.add(
        models.PaperPosition(
            portfolio_id=portfolio.id, asset_id=tracked.id, quantity=50, average_cost=1000
        )
    )
    session.flush()

    scorer = ResearchPriorityScorer()
    scores = {}
    for asset in (tracked, ignored):
        change = next(
            c
            for c in ChangeDetector().detect_for_asset(session, asset, NOW)
            if c.change_type is ChangeType.PRICE_SHOCK
        )
        scores[asset.ticker] = scorer.score(session, change, NOW)

    assert scores["TRACKED"].score > scores["IGNORED"].score
    assert scores["TRACKED"].portfolio_impact == pytest.approx(0.5)
    assert scores["IGNORED"].portfolio_impact == 0.0


def test_novelty_falls_as_research_gets_more_recent(session: Session) -> None:
    fresh = _asset(session, "FRESH")
    stale = _asset(session, "STALE")
    for asset in (fresh, stale):
        _add_closes(session, asset, [100.0, 110.0])
    _research_doc(session, fresh, days_ago=1)
    _research_doc(session, stale, days_ago=200)

    scorer = ResearchPriorityScorer()
    results = {}
    for asset in (fresh, stale):
        change = next(
            c
            for c in ChangeDetector().detect_for_asset(session, asset, NOW)
            if c.change_type is ChangeType.PRICE_SHOCK
        )
        results[asset.ticker] = scorer.score(session, change, NOW)

    assert results["STALE"].novelty > results["FRESH"].novelty
    assert results["FRESH"].novelty < 0.1


def test_weights_are_configurable(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])
    change = next(
        c
        for c in ChangeDetector().detect_for_asset(session, asset, NOW)
        if c.change_type is ChangeType.PRICE_SHOCK
    )

    importance_only = PriorityWeights(
        importance=1.0, novelty=0.0, portfolio_impact=0.0, watchlist_relevance=0.0
    )
    priority = ResearchPriorityScorer(importance_only).score(session, change, NOW)

    assert priority.score == pytest.approx(priority.importance)


# -- queue --------------------------------------------------------------------


def test_queue_is_ordered_highest_priority_first(session: Session) -> None:
    engine = ResearchIntelligenceEngine()
    big = _asset(session, "BIGMOVE")
    small = _asset(session, "SMALLMOVE")
    _add_closes(session, big, [100.0, 200.0])
    _add_closes(session, small, [100.0, 106.0])

    engine.scan(session, now=NOW)
    session.commit()

    queue = get_queue(session)
    scores = [float(e.score) for e in queue]
    assert scores == sorted(scores, reverse=True)
    assert queue[0].ticker == "BIGMOVE"


def test_scan_is_idempotent(session: Session) -> None:
    """Re-running detection refreshes priorities instead of duplicating."""
    engine = ResearchIntelligenceEngine()
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])

    first = engine.scan(session, now=NOW)
    session.commit()
    second = engine.scan(session, now=NOW)
    session.commit()

    assert first.entries_created > 0
    assert second.entries_created == 0
    assert second.entries_refreshed == first.entries_created
    assert len(get_queue(session)) == first.entries_created


def test_regime_change_only_reaches_tracked_assets(session: Session) -> None:
    """Fanning a market-wide change across every asset would drown the queue."""
    watched = _asset(session, "WATCHED")
    unwatched = _asset(session, "UNWATCHED")
    _research_doc(session, watched, days_ago=1)
    _research_doc(session, unwatched, days_ago=1)
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, watched)
    _regime(session, "BULLISH", NOW - dt.timedelta(days=2))
    _regime(session, "BEARISH", NOW)

    ResearchIntelligenceEngine().scan(session, now=NOW)
    session.commit()

    regime_entries = [e for e in get_queue(session) if e.change_type == "regime_change"]
    assert [e.ticker for e in regime_entries] == ["WATCHED"]


def test_queue_lifecycle(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])
    ResearchIntelligenceEngine().scan(session, now=NOW)
    session.commit()

    entry = next_entry(session)
    assert entry is not None
    assert entry.status == STATUS_PENDING

    mark_done(session, entry, research_document_id=None, now=NOW)
    session.commit()

    assert entry.status == "done"
    assert entry.processed_at is not None
    assert entry.id not in [e.id for e in get_queue(session)]


def test_dismissal_keeps_an_auditable_note(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])
    ResearchIntelligenceEngine().scan(session, now=NOW)
    session.commit()
    entry = next_entry(session)
    assert entry is not None

    dismiss(session, entry, note="known index rebalance", now=NOW)
    session.commit()

    assert entry.status == "dismissed"
    assert entry.note == "known index rebalance"


def test_a_done_entry_can_be_raised_again_by_a_new_change(session: Session) -> None:
    asset = _asset(session)
    _add_closes(session, asset, [100.0, 110.0])
    engine = ResearchIntelligenceEngine()
    engine.scan(session, now=NOW)
    session.commit()
    for entry in get_queue(session):
        mark_done(session, entry, now=NOW)
    session.commit()

    result = engine.scan(session, now=NOW)
    session.commit()

    assert result.entries_created > 0  # closed entries don't suppress new detections
