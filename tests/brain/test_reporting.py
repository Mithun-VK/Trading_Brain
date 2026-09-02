from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from brain.reporting.engine import ReportingEngine
from brain.reporting.links import LinkResolver
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio, record_buy
from data.storage.price_repository import upsert_price_bars
from models.base import Base
from tests.fakes import FakeKnowledgeStore

AS_OF = dt.date(2026, 3, 15)
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.UTC)


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


def _prices(session: Session, asset: models.Asset, closes: list[float]) -> None:
    upsert_price_bars(
        session,
        asset.id,
        [
            PriceBar(
                ts=dt.datetime.combine(
                    AS_OF - dt.timedelta(days=len(closes) - i), dt.time.min, tzinfo=dt.UTC
                ),
                open=c, high=c, low=c, close=c, volume=100, interval="1d", source="test",
            )
            for i, c in enumerate(closes)
        ],
    )
    session.flush()


# -- link safety --------------------------------------------------------------


def test_links_are_only_emitted_for_notes_that_exist() -> None:
    """The hard requirement: never create a broken link."""
    store = FakeKnowledgeStore({"08 Research/RELIANCE.md": "body"})
    resolver = LinkResolver(store)

    assert resolver.link("08 Research/RELIANCE.md", "Research") == (
        "[[08 Research/RELIANCE|Research]]"
    )
    assert resolver.link("08 Research/MISSING.md", "Missing") == "Missing"
    assert resolver.link(None, "Nothing") == "Nothing"


def test_without_a_knowledge_store_everything_degrades_to_plain_text() -> None:
    resolver = LinkResolver(None)

    assert resolver.link("anything.md", "Label") == "Label"
    assert resolver.link_by_name("RELIANCE") == "RELIANCE"


def test_link_by_name_matches_basenames() -> None:
    store = FakeKnowledgeStore({"02 Companies/India/RELIANCE.md": "body"})
    resolver = LinkResolver(store)

    assert resolver.link_by_name("RELIANCE") == "[[RELIANCE]]"
    assert resolver.link_by_name("UNKNOWN") == "UNKNOWN"


def test_an_unreachable_vault_disables_links_without_failing() -> None:
    class _BrokenStore(FakeKnowledgeStore):
        def list_notes(self, folder: str | None = None) -> list[str]:
            from integrations.obsidian.errors import ObsidianConnectionError

            raise ObsidianConnectionError("vault down")

    resolver = LinkResolver(_BrokenStore())

    assert resolver.link("x.md", "Label") == "Label"


# -- report structure ---------------------------------------------------------


def test_daily_report_has_all_sections_even_when_empty(session: Session) -> None:
    """An omitted section is ambiguous; an explicit 'none' is not."""
    report = ReportingEngine().daily(session, as_of=AS_OF)

    for heading in ("Market Regime", "Major Moves", "Signals", "Research",
                    "Thesis Changes", "Paper Portfolio"):
        assert f"## {heading}" in report.markdown
    assert "No regime observation recorded yet." in report.markdown
    assert "No signals generated in this period." in report.markdown
    assert "No paper portfolio configured." in report.markdown


def test_report_is_deterministic(session: Session) -> None:
    asset = _asset(session)
    _prices(session, asset, [100.0, 110.0])
    session.commit()

    first = ReportingEngine().daily(session, as_of=AS_OF)
    second = ReportingEngine().daily(session, as_of=AS_OF)

    assert first.markdown == second.markdown


def test_daily_note_path_uses_the_daily_folder(session: Session) -> None:
    report = ReportingEngine().daily(session, as_of=AS_OF)

    assert report.note_path == "09 Reviews/Daily/2026-03-15.md"


def test_weekly_and_monthly_windows(session: Session) -> None:
    weekly = ReportingEngine().weekly(session, as_of=AS_OF)
    monthly = ReportingEngine().monthly(session, as_of=AS_OF)

    assert weekly.period_start == dt.date(2026, 3, 9)
    assert monthly.period_start == dt.date(2026, 3, 1)
    assert weekly.note_path.startswith("09 Reviews/Weekly/")
    assert monthly.note_path.startswith("09 Reviews/Monthly/")


def test_report_includes_the_disclaimer(session: Session) -> None:
    report = ReportingEngine().daily(session, as_of=AS_OF)

    assert "not financial advice" in report.markdown
    assert "Rule 12" in report.markdown


# -- content ------------------------------------------------------------------


def test_regime_section_is_labelled_descriptive(session: Session) -> None:
    session.add(
        models.MarketRegimeObservation(
            observed_at=NOW, regime="BULLISH",
            volatility_regime="LOW_VOLATILITY", risk_regime="RISK_ON",
        )
    )
    session.commit()

    markdown = ReportingEngine().daily(session, as_of=AS_OF).markdown

    assert "**BULLISH**" in markdown
    assert "not forecasts" in markdown


def test_movers_section_ranks_by_absolute_move(session: Session) -> None:
    big = _asset(session, "BIG")
    small = _asset(session, "SMALL")
    _prices(session, big, [100.0, 130.0])
    _prices(session, small, [100.0, 101.0])
    session.commit()

    report = ReportingEngine().daily(session, as_of=AS_OF)

    assert report.sections["movers"] == 2
    big_index = report.markdown.index("BIG")
    small_index = report.markdown.index("SMALL")
    assert big_index < small_index


def test_signals_section_lists_evidence_counts(session: Session) -> None:
    asset = _asset(session)
    session.add(
        models.Signal(
            asset_id=asset.id, signal_type="rule", category="ACCUMULATE",
            confidence=0.8, reasoning="thesis intact",
            evidence=[{"kind": "quant", "detail": "d", "stance": "supports"}],
            value={}, source="engine", status="active", generated_at=NOW,
        )
    )
    session.commit()

    report = ReportingEngine().daily(session, as_of=AS_OF)

    assert "**ACCUMULATE**" in report.markdown
    assert "1 evidence items" in report.markdown
    assert "thesis intact" in report.markdown
    assert report.sections["signals"] == 1


def test_thesis_changes_render_the_transition(session: Session) -> None:
    asset = _asset(session)
    thesis = models.Thesis(
        asset_id=asset.id, title="Reliance upcycle", status="active",
        current_assessment="THESIS_WEAKENED",
    )
    session.add(thesis)
    session.flush()
    session.add(
        models.ThesisReviewRecord(
            thesis_id=thesis.id, asset_id=asset.id,
            previous_assessment="THESIS_INTACT", assessment="THESIS_WEAKENED",
            reviewed_at=NOW,
        )
    )
    session.commit()

    markdown = ReportingEngine().daily(session, as_of=AS_OF).markdown

    assert "THESIS_INTACT → **THESIS_WEAKENED**" in markdown


def test_portfolio_section_flags_unpriced_positions(session: Session) -> None:
    asset = _asset(session)
    portfolio = create_portfolio(session, "Core", initial_cash=100_000.0)
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=NOW)
    session.commit()

    markdown = ReportingEngine().daily(session, as_of=AS_OF).markdown

    assert "### Core" in markdown
    assert "no price available" in markdown


def test_monthly_report_carries_learning_caveats(session: Session) -> None:
    session.add(
        models.LearningReview(
            kind="monthly",
            period_start=dt.date(2026, 2, 1),
            period_end=dt.date(2026, 2, 28),
            generated_at=NOW,
            metrics={
                "signal_accuracy": {
                    "overall": {
                        "accuracy": None, "sample_size": 0,
                        "caveat": "No resolved outcomes yet.",
                    }
                },
                "thesis_accuracy": {"total_theses": 2, "invalidated": 0,
                                    "median_days_to_invalidation": None},
                "research_outcomes": {
                    "why_not_accuracy": "no falsifiable directional prediction"
                },
            },
        )
    )
    session.commit()

    markdown = ReportingEngine().monthly(session, as_of=AS_OF).markdown

    assert "no resolved outcomes yet" in markdown
    assert "No resolved outcomes yet." in markdown
    assert "not** an accuracy score" in markdown
    assert "none recorded" in markdown  # median days, not a fake 0


def test_publish_writes_into_the_vault(session: Session) -> None:
    store = FakeKnowledgeStore()
    engine = ReportingEngine(store)

    report = engine.daily(session, as_of=AS_OF)
    path = engine.publish(report)

    assert path == "09 Reviews/Daily/2026-03-15.md"
    assert store.notes[path] == report.markdown


def test_publish_without_a_store_returns_none_but_keeps_markdown(
    session: Session,
) -> None:
    engine = ReportingEngine(None)
    report = engine.daily(session, as_of=AS_OF)

    assert engine.publish(report) is None
    assert report.markdown  # the caller still has the content


def test_report_links_to_a_real_research_note(session: Session) -> None:
    asset = _asset(session)
    document = models.ResearchDocument(
        asset_id=asset.id, title="Reliance research", summary="s",
        obsidian_note_path="08 Research/RELIANCE-2026-03-15.md", source="claude",
    )
    session.add(document)
    session.commit()
    document.created_at = NOW
    session.commit()

    store = FakeKnowledgeStore({"08 Research/RELIANCE-2026-03-15.md": "body"})
    markdown = ReportingEngine(store).daily(session, as_of=AS_OF).markdown

    assert "[[08 Research/RELIANCE-2026-03-15|Reliance research]]" in markdown


def test_a_research_note_missing_from_the_vault_is_not_linked(session: Session) -> None:
    asset = _asset(session)
    document = models.ResearchDocument(
        asset_id=asset.id, title="Ghost research", summary="s",
        obsidian_note_path="08 Research/GONE.md", source="claude",
    )
    session.add(document)
    session.commit()
    document.created_at = NOW
    session.commit()

    markdown = ReportingEngine(FakeKnowledgeStore()).daily(session, as_of=AS_OF).markdown

    assert "Ghost research" in markdown
    assert "[[08 Research/GONE" not in markdown
