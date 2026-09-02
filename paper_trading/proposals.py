"""Paper trade proposals and the human-approval gate.

The whole point of this module is the gate. A signal can *suggest* a
position change; only a person can approve it; only an approved proposal
can execute. `execute_proposal` refuses every other status, so the approval
step cannot be skipped -- not by a job, not by an agent, not by a caller
that forgot (Rule 7).

Execution then writes rows via the Phase 16 accounting functions and
nothing else. There is no broker anywhere in this path (Rule 8).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.signals.schemas import SignalCategory
from config.logging import get_logger
from data.storage.portfolio_repository import get_position, record_buy, record_sell
from models.asset import Asset
from models.paper_portfolio import PaperPortfolio, PaperTransaction
from models.paper_trade_proposal import (
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_REJECTED,
    PaperTradeProposal,
)
from models.signal import Signal

logger = get_logger("paper_trading")


class ProposalError(Exception):
    """A proposal operation was not permitted."""


class ApprovalRequiredError(ProposalError):
    """Attempted to execute a proposal a human has not approved."""


# Which attention signals can suggest a position change, and how.
# WATCH / RESEARCH / THESIS_REVIEW deliberately produce nothing: they are
# prompts to look, not to alter a position.
_ACCUMULATE_FRACTION = 0.05  # of portfolio equity
_REDUCE_FRACTION = 0.25  # of the existing position


@dataclass(frozen=True)
class ProposalDraft:
    side: str
    quantity: float
    rationale: str


def propose_from_signal(
    session: Session,
    signal: Signal,
    portfolio: PaperPortfolio,
    asset: Asset,
    price: float,
    now: dt.datetime | None = None,
    stop_price: float | None = None,
) -> PaperTradeProposal | None:
    """Turn an attention signal into a proposal awaiting approval.

    Returns None when the signal is not a position-change signal, or when
    there is nothing sensible to propose (no cash, no position to trim).
    """
    now = now or dt.datetime.now(dt.UTC)
    if price <= 0:
        raise ProposalError("A proposal needs a positive reference price")

    draft = _draft_for(session, signal, portfolio, asset, price)
    if draft is None:
        return None

    proposal = PaperTradeProposal(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        ticker=asset.ticker,
        side=draft.side,
        quantity=round(draft.quantity, 6),
        reference_price=price,
        stop_price=stop_price,
        status=STATUS_PENDING,
        rationale=draft.rationale,
        source_signal_id=signal.id,
    )
    session.add(proposal)
    session.flush()

    logger.info(
        "paper_proposal_created",
        operation="propose_from_signal",
        status="pending_approval",
        ticker=asset.ticker,
        side=draft.side,
    )
    return proposal


def _draft_for(
    session: Session,
    signal: Signal,
    portfolio: PaperPortfolio,
    asset: Asset,
    price: float,
) -> ProposalDraft | None:
    category = signal.category
    position = get_position(session, portfolio, asset)
    held = float(position.quantity) if position else 0.0

    if category == SignalCategory.ACCUMULATE:
        cash = float(portfolio.cash_balance)
        budget = min(float(portfolio.initial_cash) * _ACCUMULATE_FRACTION, cash)
        quantity = budget / price
        if quantity <= 0:
            return None
        return ProposalDraft(
            side="buy",
            quantity=quantity,
            rationale=(
                f"ACCUMULATE signal (confidence {float(signal.confidence or 0):.2f}). "
                f"{signal.reasoning}"
            ),
        )

    if category == SignalCategory.REDUCE:
        if held <= 0:
            return None
        return ProposalDraft(
            side="sell",
            quantity=held * _REDUCE_FRACTION,
            rationale=(
                f"REDUCE signal (confidence {float(signal.confidence or 0):.2f}). "
                f"{signal.reasoning}"
            ),
        )

    if category == SignalCategory.EXIT_REVIEW:
        if held <= 0:
            return None
        return ProposalDraft(
            side="sell",
            quantity=held,
            rationale=(
                f"EXIT_REVIEW signal (confidence {float(signal.confidence or 0):.2f}). "
                f"{signal.reasoning}"
            ),
        )

    # WATCH / RESEARCH / THESIS_REVIEW -> nothing to propose.
    return None


def approve(
    session: Session,
    proposal: PaperTradeProposal,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> PaperTradeProposal:
    """Record a human's approval. Does not execute -- that is a separate,
    explicit step.
    """
    if proposal.status != STATUS_PENDING:
        raise ProposalError(
            f"Only a pending proposal can be approved (status is {proposal.status!r})"
        )
    proposal.status = STATUS_APPROVED
    proposal.decided_at = now or dt.datetime.now(dt.UTC)
    proposal.decision_note = note
    session.flush()
    return proposal


def reject(
    session: Session,
    proposal: PaperTradeProposal,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> PaperTradeProposal:
    if proposal.status not in (STATUS_PENDING, STATUS_APPROVED):
        raise ProposalError(f"Cannot reject a proposal that is {proposal.status!r}")
    proposal.status = STATUS_REJECTED
    proposal.decided_at = now or dt.datetime.now(dt.UTC)
    proposal.decision_note = note
    session.flush()
    return proposal


def expire(
    session: Session, proposal: PaperTradeProposal, now: dt.datetime | None = None
) -> PaperTradeProposal:
    """Close out a stale proposal. Prices move; an old suggestion should not
    sit there looking actionable.
    """
    if proposal.status != STATUS_PENDING:
        raise ProposalError(f"Cannot expire a proposal that is {proposal.status!r}")
    proposal.status = STATUS_EXPIRED
    proposal.decided_at = now or dt.datetime.now(dt.UTC)
    session.flush()
    return proposal


def execute_proposal(
    session: Session,
    proposal: PaperTradeProposal,
    fill_price: float | None = None,
    fees: float = 0.0,
    now: dt.datetime | None = None,
) -> PaperTransaction:
    """Execute an **approved** proposal as a simulated transaction.

    Raises `ApprovalRequiredError` for anything not explicitly approved.
    This is the only path from a proposal to a position change.
    """
    if proposal.status != STATUS_APPROVED:
        raise ApprovalRequiredError(
            f"Proposal {proposal.id} is {proposal.status!r}. A paper trade may only "
            "execute after explicit human approval (Rule 7)."
        )

    now = now or dt.datetime.now(dt.UTC)
    price = fill_price if fill_price is not None else float(proposal.reference_price)
    portfolio = session.get(PaperPortfolio, proposal.portfolio_id)
    asset = session.get(Asset, proposal.asset_id)
    if portfolio is None or asset is None:
        raise ProposalError("Proposal references a missing portfolio or asset")

    if proposal.side == "buy":
        transaction = record_buy(
            session, portfolio, asset,
            quantity=float(proposal.quantity), price=price, fees=fees,
            executed_at=now, note=f"proposal:{proposal.id}",
        )
    elif proposal.side == "sell":
        transaction = record_sell(
            session, portfolio, asset,
            quantity=float(proposal.quantity), price=price, fees=fees,
            executed_at=now, note=f"proposal:{proposal.id}",
        )
    else:
        raise ProposalError(f"Unknown proposal side {proposal.side!r}")

    proposal.status = STATUS_EXECUTED
    proposal.executed_transaction_id = transaction.id
    session.flush()

    logger.info(
        "paper_proposal_executed",
        operation="execute_proposal",
        status="ok",
        ticker=proposal.ticker,
        side=proposal.side,
    )
    return transaction


def list_proposals(
    session: Session,
    portfolio: PaperPortfolio | None = None,
    status: str = STATUS_PENDING,
) -> list[PaperTradeProposal]:
    query = (
        select(PaperTradeProposal)
        .where(PaperTradeProposal.status == status)
        .order_by(PaperTradeProposal.created_at.desc())
    )
    if portfolio is not None:
        query = query.where(PaperTradeProposal.portfolio_id == portfolio.id)
    return list(session.scalars(query).all())
