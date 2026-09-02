from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from data.ingestion.schemas import PriceBar
from data.storage.portfolio_repository import create_portfolio, get_position, record_buy
from data.storage.price_repository import upsert_price_bars
from models.base import Base
from models.paper_trade_proposal import STATUS_APPROVED, STATUS_PENDING
from paper_trading.journal import journal_paper_fill
from paper_trading.proposals import (
    ApprovalRequiredError,
    ProposalError,
    approve,
    execute_proposal,
    expire,
    list_proposals,
    propose_from_signal,
    reject,
)
from paper_trading.tracking import get_snapshots, performance, take_snapshot

NOW = dt.datetime(2026, 3, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def asset(session: Session) -> models.Asset:
    asset = models.Asset(
        ticker="RELIANCE", exchange="NSE", asset_type="equity", name="Reliance"
    )
    session.add(asset)
    session.flush()
    return asset


@pytest.fixture
def portfolio(session: Session) -> models.PaperPortfolio:
    return create_portfolio(session, "Core", initial_cash=100_000.0)


def _signal(
    session: Session, asset: models.Asset, category: str, confidence: float = 0.8
) -> models.Signal:
    signal = models.Signal(
        asset_id=asset.id,
        signal_type="rule",
        category=category,
        confidence=confidence,
        reasoning=f"{category} because of evidence",
        evidence=[{"kind": "quant", "detail": "d", "stance": "supports"}],
        value={},
        source="brain.signals.engine",
        status="active",
        generated_at=NOW,
    )
    session.add(signal)
    session.flush()
    return signal


# -- the approval gate --------------------------------------------------------


def test_a_proposal_starts_pending_approval(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")

    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)

    assert proposal is not None
    assert proposal.status == STATUS_PENDING
    assert proposal.source_signal_id == signal.id


def test_an_unapproved_proposal_cannot_execute(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    """Rule 7: no path from suggestion to position without a human."""
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None

    with pytest.raises(ApprovalRequiredError, match="human approval"):
        execute_proposal(session, proposal, now=NOW)

    assert get_position(session, portfolio, asset) is None
    assert float(portfolio.cash_balance) == 100_000.0


def test_a_rejected_proposal_cannot_execute(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None
    reject(session, proposal, note="not now", now=NOW)

    with pytest.raises(ApprovalRequiredError):
        execute_proposal(session, proposal, now=NOW)


def test_approval_alone_does_not_execute(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    """Approving and executing are deliberately separate steps."""
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None

    approve(session, proposal, note="ok", now=NOW)
    session.commit()

    assert proposal.status == STATUS_APPROVED
    assert get_position(session, portfolio, asset) is None  # nothing happened yet


def test_approved_proposal_executes_into_a_simulated_position(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None
    approve(session, proposal, now=NOW)

    transaction = execute_proposal(session, proposal, now=NOW)
    session.commit()

    position = get_position(session, portfolio, asset)
    assert position is not None
    assert float(position.quantity) == pytest.approx(float(proposal.quantity))
    assert proposal.status == "executed"
    assert proposal.executed_transaction_id == transaction.id
    assert float(portfolio.cash_balance) < 100_000.0


def test_a_proposal_cannot_execute_twice(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None
    approve(session, proposal, now=NOW)
    execute_proposal(session, proposal, now=NOW)

    with pytest.raises(ApprovalRequiredError):
        execute_proposal(session, proposal, now=NOW)


def test_an_executed_proposal_cannot_be_re_approved(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None
    approve(session, proposal, now=NOW)
    execute_proposal(session, proposal, now=NOW)

    with pytest.raises(ProposalError, match="Only a pending proposal"):
        approve(session, proposal, now=NOW)


def test_stale_proposals_can_be_expired(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    assert proposal is not None

    expire(session, proposal, now=NOW)

    assert proposal.status == "expired"
    with pytest.raises(ApprovalRequiredError):
        execute_proposal(session, proposal, now=NOW)


# -- signal -> proposal mapping ----------------------------------------------


def test_attention_only_signals_propose_nothing(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    """WATCH/RESEARCH/THESIS_REVIEW are prompts to look, not to trade."""
    for category in ("WATCH", "RESEARCH", "THESIS_REVIEW"):
        signal = _signal(session, asset, category)
        assert (
            propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
            is None
        )


def test_reduce_proposes_a_partial_sell(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=100, price=500.0, executed_at=NOW)
    signal = _signal(session, asset, "REDUCE")

    proposal = propose_from_signal(session, signal, portfolio, asset, price=520.0, now=NOW)

    assert proposal is not None
    assert proposal.side == "sell"
    assert float(proposal.quantity) == pytest.approx(25.0)  # 25% of 100


def test_exit_review_proposes_a_full_close(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=40, price=500.0, executed_at=NOW)
    signal = _signal(session, asset, "EXIT_REVIEW")

    proposal = propose_from_signal(session, signal, portfolio, asset, price=400.0, now=NOW)

    assert proposal is not None
    assert proposal.side == "sell"
    assert float(proposal.quantity) == pytest.approx(40.0)


def test_sell_signals_propose_nothing_without_a_position(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "REDUCE")

    assert (
        propose_from_signal(session, signal, portfolio, asset, price=500.0, now=NOW) is None
    )


def test_proposal_rationale_carries_the_signal_reasoning(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE", confidence=0.62)
    proposal = propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)

    assert proposal is not None
    assert "0.62" in proposal.rationale
    assert "evidence" in proposal.rationale


def test_list_pending_proposals(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    signal = _signal(session, asset, "ACCUMULATE")
    propose_from_signal(session, signal, portfolio, asset, price=1000.0, now=NOW)
    session.commit()

    assert len(list_proposals(session, portfolio)) == 1


# -- journal integration ------------------------------------------------------


def test_a_paper_buy_opens_a_journal_trade(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    trade = journal_paper_fill(
        session, portfolio, asset, "buy", quantity=10, price=1000.0,
        executed_at=NOW, stop_price=900.0,
    )
    session.commit()

    assert trade is not None
    assert trade.status == "open"
    assert float(trade.risk_amount) == pytest.approx(1000.0)  # 100 x 10


def test_a_full_exit_closes_the_journal_trade_with_an_r_multiple(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    journal_paper_fill(
        session, portfolio, asset, "buy", quantity=10, price=1000.0,
        executed_at=NOW, stop_price=900.0,
    )

    trade = journal_paper_fill(
        session, portfolio, asset, "sell", quantity=10, price=1200.0,
        executed_at=NOW, remaining_quantity=0,
    )
    session.commit()

    assert trade is not None
    assert trade.status == "closed"
    assert trade.result == "win"
    assert float(trade.r_multiple) == pytest.approx(2.0)  # +200 on 100 risk


def test_a_trade_without_a_stop_gets_no_invented_r_multiple(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    """Back-fitting an R-multiple would fabricate risk that was never defined."""
    journal_paper_fill(
        session, portfolio, asset, "buy", quantity=10, price=1000.0, executed_at=NOW
    )

    trade = journal_paper_fill(
        session, portfolio, asset, "sell", quantity=10, price=1200.0,
        executed_at=NOW, remaining_quantity=0,
    )
    session.commit()

    assert trade is not None
    assert trade.result == "win"
    assert trade.r_multiple is None
    assert trade.risk_amount is None


def test_a_partial_exit_leaves_the_trade_open(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    journal_paper_fill(
        session, portfolio, asset, "buy", quantity=10, price=1000.0, executed_at=NOW
    )

    trade = journal_paper_fill(
        session, portfolio, asset, "sell", quantity=4, price=1100.0,
        executed_at=NOW, remaining_quantity=6,
    )
    session.commit()

    assert trade is not None
    assert trade.status == "open"  # a trim is not a completed trade


def test_averaging_in_does_not_open_a_second_trade(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    first = journal_paper_fill(
        session, portfolio, asset, "buy", quantity=10, price=1000.0, executed_at=NOW
    )
    second = journal_paper_fill(
        session, portfolio, asset, "buy", quantity=5, price=1100.0, executed_at=NOW
    )
    session.commit()

    assert first is not None and second is not None
    assert first.id == second.id
    assert session.query(models.Trade).count() == 1


# -- tracking -----------------------------------------------------------------


def _price(session: Session, asset: models.Asset, close: float, day: int = 1) -> None:
    upsert_price_bars(
        session,
        asset.id,
        [
            PriceBar(
                ts=dt.datetime(2026, 3, day, tzinfo=dt.UTC),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=100,
                interval="1d",
                source="test",
            )
        ],
    )
    session.flush()


def test_snapshot_records_equity_and_exposure(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=NOW)
    _price(session, asset, 1200.0)

    snapshot = take_snapshot(session, portfolio, as_of=dt.date(2026, 3, 1))
    session.commit()

    assert float(snapshot.equity) == pytest.approx(102_000.0)  # 90k cash + 12k
    assert float(snapshot.exposure) == pytest.approx(12_000 / 102_000)
    assert snapshot.unpriced_positions == 0


def test_snapshots_are_idempotent_per_day(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    take_snapshot(session, portfolio, as_of=dt.date(2026, 3, 1))
    take_snapshot(session, portfolio, as_of=dt.date(2026, 3, 1))
    session.commit()

    assert len(get_snapshots(session, portfolio)) == 1


def test_snapshot_flags_unpriced_positions(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=NOW)
    # No price bars stored at all.

    snapshot = take_snapshot(session, portfolio, as_of=dt.date(2026, 3, 1))
    session.commit()

    assert snapshot.unpriced_positions == 1


def test_drawdown_needs_history_and_is_computed_from_snapshots(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=50, price=1000.0, executed_at=NOW)
    for day, close in ((1, 1000.0), (2, 1200.0), (3, 700.0), (4, 800.0)):
        _price(session, asset, close, day=day)
        take_snapshot(session, portfolio, as_of=dt.date(2026, 3, day))
    session.commit()

    summary = performance(session, portfolio)

    assert summary.snapshots == 4
    assert summary.max_drawdown < 0
    assert summary.fully_priced is True


def test_performance_without_snapshots_reports_zeros_not_guesses(
    session: Session, portfolio: models.PaperPortfolio
) -> None:
    summary = performance(session, portfolio)

    assert summary.snapshots == 0
    assert summary.total_return == 0.0
    assert summary.sharpe == 0.0
    assert summary.current_equity == 100_000.0


def test_performance_reports_when_a_valuation_was_incomplete(
    session: Session, portfolio: models.PaperPortfolio, asset: models.Asset
) -> None:
    record_buy(session, portfolio, asset, quantity=10, price=1000.0, executed_at=NOW)
    take_snapshot(session, portfolio, as_of=dt.date(2026, 3, 1))
    session.commit()

    assert performance(session, portfolio).fully_priced is False
