from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.signals.engine import SignalEngine
from brain.signals.schemas import (
    FORBIDDEN_CATEGORIES,
    Evidence,
    EvidenceKind,
    EvidenceStance,
    GeneratedSignal,
    SignalCategory,
    SignalError,
    build_signal,
    compute_confidence,
)
from data.ingestion.schemas import PriceBar
from data.storage.price_repository import upsert_price_bars
from data.storage.signal_repository import (
    acknowledge,
    dismiss,
    get_active_signals,
    save_signal,
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


def _closes(session: Session, asset: models.Asset, closes: list[float]) -> None:
    bars = [
        PriceBar(
            ts=(NOW - dt.timedelta(days=len(closes) - i)).replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1000,
            interval="1d",
            source="test",
        )
        for i, close in enumerate(closes)
    ]
    upsert_price_bars(session, asset.id, bars)
    session.flush()


def _rising(count: int = 260, start: float = 100.0) -> list[float]:
    return [start * (1.004**i) for i in range(count)]


def _falling(count: int = 260, start: float = 300.0) -> list[float]:
    return [start * (0.996**i) for i in range(count)]


def _regime(session: Session, trend: str, risk: str = "RISK_ON") -> None:
    session.add(
        models.MarketRegimeObservation(
            observed_at=NOW,
            regime=trend,
            volatility_regime="LOW_VOLATILITY",
            risk_regime=risk,
        )
    )
    session.flush()


def _thesis(session: Session, asset: models.Asset, assessment: str) -> models.Thesis:
    thesis = models.Thesis(
        asset_id=asset.id,
        title=f"{asset.ticker} thesis",
        status="active",
        current_assessment=assessment,
        last_reviewed_at=NOW - dt.timedelta(days=1),
    )
    session.add(thesis)
    session.flush()
    return thesis


def _hold(session: Session, asset: models.Asset, avg_cost: float, quantity: float = 10):
    portfolio = models.PaperPortfolio(
        name=f"P{asset.id}", initial_cash=100_000, cash_balance=50_000
    )
    session.add(portfolio)
    session.flush()
    position = models.PaperPosition(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        quantity=quantity,
        average_cost=avg_cost,
    )
    session.add(position)
    session.flush()
    return position


def _pe(session: Session, asset: models.Asset, value: float) -> None:
    session.add(
        models.FinancialMetric(
            asset_id=asset.id,
            metric_name="pe_ratio",
            period="TTM",
            value=value,
            as_of_date=NOW.date(),
            source="test",
        )
    )
    session.flush()


# -- the core safety property -------------------------------------------------


def test_no_execution_categories_exist() -> None:
    """Rules 7/8: the engine must be incapable of telling anyone to trade."""
    categories = set(SignalEngine.categories())

    assert categories == {
        "WATCH",
        "RESEARCH",
        "ACCUMULATE",
        "REDUCE",
        "EXIT_REVIEW",
        "THESIS_REVIEW",
    }
    assert not categories & FORBIDDEN_CATEGORIES


def test_an_execution_shaped_signal_cannot_be_constructed() -> None:
    with pytest.raises(SignalError, match="execution"):
        GeneratedSignal(
            asset_id=1,
            ticker="X",
            category="BUY",  # type: ignore[arg-type]
            reasoning="should be impossible",
            evidence=[Evidence(kind=EvidenceKind.QUANT, detail="anything")],
        )


def test_a_signal_without_evidence_cannot_be_constructed() -> None:
    """Rule 10: every signal must be traceable to what produced it."""
    with pytest.raises(SignalError, match="no evidence"):
        GeneratedSignal(
            asset_id=1,
            ticker="X",
            category=SignalCategory.WATCH,
            reasoning="unsupported claim",
            evidence=[],
        )


def test_storing_an_evidence_free_signal_is_refused(session: Session) -> None:
    asset = _asset(session)
    signal = build_signal(
        asset_id=asset.id,
        ticker=asset.ticker,
        category=SignalCategory.WATCH,
        reasoning="r",
        evidence=[Evidence(kind=EvidenceKind.QUANT, detail="d")],
        rule="watch",
    )
    object.__setattr__(signal, "evidence", [])  # bypass the constructor guard

    with pytest.raises(SignalError, match="no evidence"):
        save_signal(session, signal, NOW)


# -- confidence ---------------------------------------------------------------


def test_confidence_reflects_the_evidence_balance() -> None:
    supports = Evidence(kind=EvidenceKind.QUANT, detail="a")
    contradicts = Evidence(
        kind=EvidenceKind.QUANT, detail="b", stance=EvidenceStance.CONTRADICTS
    )

    assert compute_confidence([supports, supports]) == 1.0
    assert compute_confidence([supports, contradicts]) == 0.5
    assert compute_confidence([]) == 0.0


def test_unknown_evidence_lowers_confidence_rather_than_passing_silently() -> None:
    """Rule 4/11: a missing number must never read as a passing grade."""
    supports = Evidence(kind=EvidenceKind.QUANT, detail="a")
    unknown = Evidence(kind=EvidenceKind.VALUATION, detail="?", stance=EvidenceStance.UNKNOWN)

    full = compute_confidence([supports])
    partial = compute_confidence([supports, unknown])

    assert partial < full
    assert partial == pytest.approx(1 / 1.5, abs=1e-3)


# -- individual rules ---------------------------------------------------------


def test_accumulate_fires_on_the_worked_example(session: Session) -> None:
    """thesis intact + bullish + positive momentum + acceptable valuation."""
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 22.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.ACCUMULATE
    assert signal.confidence > 0.7
    kinds = {e.kind for e in signal.evidence}
    assert kinds == {
        EvidenceKind.THESIS,
        EvidenceKind.REGIME,
        EvidenceKind.QUANT,
        EvidenceKind.VALUATION,
    }
    # A relentless rise is overbought by construction, and the rule says so
    # rather than only listing what supports it. Confidence drops accordingly.
    assert any("RSI" in e.detail for e in signal.contradicting)


def test_accumulate_confidence_is_full_when_nothing_contradicts(
    session: Session,
) -> None:
    asset = _asset(session)
    # Rise, then a mild pullback: 20-day momentum stays positive while RSI
    # cools out of overbought territory, so nothing contradicts.
    rise = _rising(250)
    pullback = [rise[-1] * (0.997 ** (i + 1)) for i in range(10)]
    _closes(session, asset, rise + pullback)
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 22.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.ACCUMULATE
    assert signal.contradicting == []
    assert signal.confidence == 1.0


def test_accumulate_is_blocked_by_an_expensive_valuation(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 120.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is None or signal.category is not SignalCategory.ACCUMULATE


def test_accumulate_with_unknown_valuation_fires_but_less_confidently(
    session: Session,
) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    # No P/E recorded at all.

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.ACCUMULATE
    assert signal.confidence < 1.0
    assert any(e.stance is EvidenceStance.UNKNOWN for e in signal.evidence)


def test_accumulate_requires_a_bullish_regime(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "SIDEWAYS")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 22.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is None or signal.category is not SignalCategory.ACCUMULATE


def test_invalidated_thesis_produces_a_thesis_review(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _thesis(session, asset, "THESIS_INVALIDATED")

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.THESIS_REVIEW


def test_long_unreviewed_thesis_produces_a_thesis_review(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    thesis = _thesis(session, asset, "THESIS_INTACT")
    thesis.last_reviewed_at = NOW - dt.timedelta(days=400)
    session.flush()

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.THESIS_REVIEW


def test_deep_underwater_position_produces_an_exit_review(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _falling())
    _hold(session, asset, avg_cost=1000.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.EXIT_REVIEW
    assert "not an instruction to sell" in signal.reasoning


def test_reduce_fires_on_risk_off_with_an_intact_thesis(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())  # not underwater, so no EXIT_REVIEW
    _regime(session, "SIDEWAYS", risk="RISK_OFF")
    _thesis(session, asset, "THESIS_INTACT")
    _hold(session, asset, avg_cost=1.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.REDUCE
    assert any(e.stance is EvidenceStance.CONTRADICTS for e in signal.evidence)


def test_reduce_defers_to_thesis_review_when_the_thesis_is_broken(
    session: Session,
) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BEARISH", risk="RISK_OFF")
    _thesis(session, asset, "THESIS_WEAKENED")
    _hold(session, asset, avg_cost=1.0)

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.THESIS_REVIEW


def test_high_priority_queue_entry_produces_a_research_signal(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    session.add(
        models.ResearchQueueEntry(
            asset_id=asset.id,
            ticker=asset.ticker,
            change_type="price_shock",
            status="pending",
            score=0.85,
            reasons=["price_shock on RELIANCE"],
            detected_at=NOW,
        )
    )
    session.flush()

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.RESEARCH


def test_watched_asset_falls_back_to_watch(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, asset)
    session.flush()

    signal = SignalEngine().generate_for_asset(session, asset, NOW)

    assert signal is not None
    assert signal.category is SignalCategory.WATCH


def test_untracked_quiet_asset_produces_no_signal(session: Session) -> None:
    """Silence is a valid answer -- the engine doesn't invent attention."""
    asset = _asset(session)
    _closes(session, asset, _rising())

    assert SignalEngine().generate_for_asset(session, asset, NOW) is None


# -- engine run ---------------------------------------------------------------


def test_run_emits_at_most_one_signal_per_asset(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _falling())
    _thesis(session, asset, "THESIS_INVALIDATED")
    _hold(session, asset, avg_cost=1000.0)
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, asset)
    session.flush()

    result = SignalEngine().run(session, now=NOW)
    session.commit()

    assert len(result.signals) == 1
    # Severity ordering: the broken thesis wins over WATCH/EXIT_REVIEW.
    assert result.signals[0].category is SignalCategory.THESIS_REVIEW


def test_run_persists_evidence_and_reasoning(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 20.0)

    SignalEngine().run(session, now=NOW)
    session.commit()

    stored = get_active_signals(session)
    assert len(stored) == 1
    row = stored[0]
    assert row.category == "ACCUMULATE"
    assert row.reasoning
    assert len(row.evidence) >= 3
    assert row.evidence[0]["kind"]
    assert float(row.confidence) > 0


def test_run_is_deterministic(session: Session) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    _regime(session, "BULLISH")
    _thesis(session, asset, "THESIS_INTACT")
    _pe(session, asset, 20.0)

    first = SignalEngine().run(session, now=NOW, persist=False)
    second = SignalEngine().run(session, now=NOW, persist=False)

    assert [(s.category, s.confidence) for s in first.signals] == [
        (s.category, s.confidence) for s in second.signals
    ]


def test_by_category_summarizes_a_run(session: Session) -> None:
    watched = _asset(session, "AAA")
    held = _asset(session, "BBB")
    _closes(session, watched, _rising())
    _closes(session, held, _falling())
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, watched)
    _hold(session, held, avg_cost=1000.0)
    session.flush()

    result = SignalEngine().run(session, now=NOW)
    session.commit()

    counts = result.by_category()
    assert counts.get("WATCH") == 1
    assert counts.get("EXIT_REVIEW") == 1


# -- lifecycle ----------------------------------------------------------------


def test_acknowledge_and_dismiss_remove_a_signal_from_the_active_list(
    session: Session,
) -> None:
    asset = _asset(session)
    _closes(session, asset, _rising())
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, asset)
    session.flush()
    SignalEngine().run(session, now=NOW)
    session.commit()

    signal = get_active_signals(session)[0]
    acknowledge(session, signal, NOW)
    session.commit()
    assert get_active_signals(session) == []

    dismiss(session, signal, NOW)
    session.commit()
    assert signal.status == "dismissed"
    assert signal.acknowledged_at is not None


def test_active_signals_can_be_filtered_by_category(session: Session) -> None:
    watched = _asset(session, "AAA")
    held = _asset(session, "BBB")
    _closes(session, watched, _rising())
    _closes(session, held, _falling())
    watchlist = create_watchlist(session, "AI")
    add_item(session, watchlist, watched)
    _hold(session, held, avg_cost=1000.0)
    session.flush()
    SignalEngine().run(session, now=NOW)
    session.commit()

    exits = get_active_signals(session, category="EXIT_REVIEW")

    assert len(exits) == 1
    assert exits[0].asset_id == held.id
