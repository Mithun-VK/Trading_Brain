"""Artifact lineage.

Answers, for any signal / paper trade / learning metric, "where did this
come from?" by walking the recorded chain:

    market data -> quant -> regime -> research -> thesis -> signal
                -> paper trade -> outcome -> learning review

Everything here is reconstructed from stored rows. Where a link genuinely
wasn't recorded, the answer is an explicit "not recorded" rather than a
plausible guess -- an invented provenance is worse than a missing one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage.price_repository import get_price_bars, normalize_ts
from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.paper_trade_proposal import PaperTradeProposal
from models.research_document import ResearchDocument
from models.research_queue import ResearchQueueEntry
from models.signal import Signal
from models.thesis import Thesis
from models.thesis_review_record import ThesisReviewRecord
from models.trade import Trade

NOT_RECORDED = "not recorded"


@dataclass
class LineageNode:
    stage: str
    summary: str
    recorded: bool = True
    reference: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "summary": self.summary,
            "recorded": self.recorded,
            **({"reference": self.reference} if self.reference else {}),
        }


def _regime_at(session: Session, when: dt.datetime) -> MarketRegimeObservation | None:
    anchor = normalize_ts(when)
    for observation in session.scalars(
        select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
    ).all():
        if normalize_ts(observation.observed_at) <= anchor:
            return observation
    return None


def signal_lineage(session: Session, signal: Signal) -> dict:
    """Why was this signal generated, and what happened afterward?"""
    asset = session.get(Asset, signal.asset_id)
    nodes: list[LineageNode] = []

    bars = get_price_bars(session, signal.asset_id, limit=1)
    nodes.append(
        LineageNode(
            stage="market_data",
            summary=(
                f"Latest stored bar {bars[-1].ts.date().isoformat()} "
                f"close {float(bars[-1].close):,.2f} (source: {bars[-1].source})"
                if bars
                else "No price history stored for this asset."
            ),
            recorded=bool(bars),
            reference={"source": bars[-1].source} if bars else {},
        )
    )

    regime = _regime_at(session, signal.generated_at)
    nodes.append(
        LineageNode(
            stage="regime",
            summary=(
                f"{regime.regime} / {regime.volatility_regime} / {regime.risk_regime} "
                f"as of {regime.observed_at.date().isoformat()}"
                if regime
                else "No regime observation existed at signal time."
            ),
            recorded=regime is not None,
        )
    )

    research = session.scalars(
        select(ResearchDocument)
        .where(ResearchDocument.asset_id == signal.asset_id)
        .order_by(ResearchDocument.created_at.desc())
    ).first()
    nodes.append(
        LineageNode(
            stage="research",
            summary=(
                f"'{research.title}' published "
                f"{normalize_ts(research.created_at).date().isoformat()}"
                if research
                else "No research document on record for this asset."
            ),
            recorded=research is not None,
            reference=(
                {"document_id": research.id, "note": research.obsidian_note_path}
                if research
                else {}
            ),
        )
    )

    thesis = session.scalars(
        select(Thesis).where(Thesis.asset_id == signal.asset_id, Thesis.status == "active")
    ).first()
    nodes.append(
        LineageNode(
            stage="thesis",
            summary=(
                f"'{thesis.title}' is {thesis.current_assessment}"
                if thesis
                else "No active thesis for this asset."
            ),
            recorded=thesis is not None,
            reference={"thesis_id": thesis.id} if thesis else {},
        )
    )

    evidence = signal.evidence or []
    nodes.append(
        LineageNode(
            stage="signal",
            summary=(
                f"{signal.category} at confidence "
                f"{float(signal.confidence):.2f} with {len(evidence)} evidence items"
                if signal.confidence is not None
                else f"{signal.category} with {len(evidence)} evidence items"
            ),
            reference={"signal_id": signal.id, "rule": signal.signal_type},
        )
    )

    proposals = list(
        session.scalars(
            select(PaperTradeProposal).where(
                PaperTradeProposal.source_signal_id == signal.id
            )
        ).all()
    )
    nodes.append(
        LineageNode(
            stage="paper_trade",
            summary=(
                "; ".join(
                    f"{p.side} {float(p.quantity):.2f} {p.ticker} ({p.status})"
                    for p in proposals
                )
                if proposals
                else "No paper trade proposal originated from this signal."
            ),
            recorded=bool(proposals),
            reference={"proposal_ids": [p.id for p in proposals]} if proposals else {},
        )
    )

    return {
        "artifact": "signal",
        "id": signal.id,
        "ticker": asset.ticker if asset else "",
        "generated_at": signal.generated_at.isoformat(),
        "reasoning": signal.reasoning,
        "evidence": evidence,
        "chain": [n.to_dict() for n in nodes],
    }


def trade_lineage(session: Session, trade: Trade) -> dict:
    """Why was this opened, what risk was defined, and what happened?"""
    asset = session.get(Asset, trade.asset_id)
    nodes: list[LineageNode] = []

    proposal = session.scalars(
        select(PaperTradeProposal)
        .where(PaperTradeProposal.asset_id == trade.asset_id)
        .order_by(PaperTradeProposal.created_at.desc())
    ).first()
    originating_signal = (
        session.get(Signal, proposal.source_signal_id)
        if proposal and proposal.source_signal_id
        else None
    )

    nodes.append(
        LineageNode(
            stage="signal",
            summary=(
                f"{originating_signal.category}: {originating_signal.reasoning}"
                if originating_signal
                else "No originating signal recorded for this trade."
            ),
            recorded=originating_signal is not None,
            reference={"signal_id": originating_signal.id} if originating_signal else {},
        )
    )
    nodes.append(
        LineageNode(
            stage="approval",
            summary=(
                f"Proposal {proposal.id} {proposal.status}"
                + (f" — {proposal.decision_note}" if proposal.decision_note else "")
                if proposal
                else "Opened directly, without a proposal (manual entry)."
            ),
            recorded=proposal is not None,
        )
    )

    if trade.stop_price is not None:
        risk_summary = (
            f"Stop {float(trade.stop_price):,.2f}, risk "
            f"{float(trade.risk_amount):,.2f}"
            if trade.risk_amount is not None
            else f"Stop {float(trade.stop_price):,.2f}"
        )
        risk_recorded = True
    else:
        risk_summary = (
            "No stop was defined, so no risk amount and no R-multiple exist. "
            "This trade is excluded from R-based statistics rather than being "
            "assigned invented risk."
        )
        risk_recorded = False
    nodes.append(LineageNode(stage="risk", summary=risk_summary, recorded=risk_recorded))

    nodes.append(
        LineageNode(
            stage="outcome",
            summary=(
                f"{trade.result} at {trade.closed_at.date().isoformat()}"
                + (
                    f", {float(trade.r_multiple):+.2f}R"
                    if trade.r_multiple is not None
                    else ", R-multiple unavailable"
                )
                if trade.status == "closed" and trade.closed_at
                else "Still open."
            ),
            recorded=trade.status == "closed",
        )
    )

    return {
        "artifact": "paper_trade",
        "id": trade.id,
        "ticker": asset.ticker if asset else "",
        "status": trade.status,
        "opened_at": trade.opened_at.isoformat(),
        "market_regime": trade.market_regime,
        "chain": [n.to_dict() for n in nodes],
    }


def thesis_lineage(session: Session, thesis: Thesis) -> dict:
    """Full assessment history for one thesis."""
    records = list(
        session.scalars(
            select(ThesisReviewRecord)
            .where(ThesisReviewRecord.thesis_id == thesis.id)
            .order_by(ThesisReviewRecord.reviewed_at.asc())
        ).all()
    )
    queue = list(
        session.scalars(
            select(ResearchQueueEntry).where(
                ResearchQueueEntry.asset_id == thesis.asset_id
            )
        ).all()
    )

    return {
        "artifact": "thesis",
        "id": thesis.id,
        "title": thesis.title,
        "current_assessment": thesis.current_assessment,
        "obsidian_note_path": thesis.obsidian_note_path,
        "review_history": [
            {
                "reviewed_at": r.reviewed_at.isoformat(),
                "from": r.previous_assessment,
                "to": r.assessment,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "reasoning": r.reasoning,
            }
            for r in records
        ],
        "history_recorded": bool(records),
        "research_triggers": [
            {"change_type": e.change_type, "score": float(e.score), "status": e.status}
            for e in queue
        ],
    }


def learning_metric_lineage(session: Session, metrics: dict) -> dict:
    """Which records produced a learning metric.

    Returns the counts and identifiers behind each figure so a reader can
    go and check it, rather than trusting a bare number.
    """
    signal_block = metrics.get("signal_accuracy", {})
    thesis_block = metrics.get("thesis_accuracy", {})

    scored_categories = list(signal_block.get("by_category", {}))
    excluded = signal_block.get("excluded_categories", [])

    signal_ids = [
        s.id
        for s in session.scalars(
            select(Signal).where(Signal.category.in_(scored_categories))
        ).all()
    ] if scored_categories else []

    review_ids = [
        r.id for r in session.scalars(select(ThesisReviewRecord)).all()
    ]

    return {
        "artifact": "learning_metrics",
        "signal_accuracy": {
            "scored_categories": scored_categories,
            "excluded_categories": excluded,
            "excluded_because": (
                "These categories make no directional claim, so they are not "
                "scored against one."
            ),
            "candidate_signal_ids": signal_ids[:50],
            "candidate_count": len(signal_ids),
        },
        "thesis_accuracy": {
            "source_table": "thesis_review_records",
            "record_ids": review_ids[:50],
            "record_count": len(review_ids),
            "reviews_recorded": thesis_block.get("reviews_recorded", 0),
        },
        "research_outcomes": {
            "source_table": "research_documents",
            "is_accuracy_score": metrics.get("research_outcomes", {}).get(
                "is_accuracy_score", False
            ),
        },
        "strategy_performance": {
            "source_table": "trades",
            "excluded": "trades without an R-multiple (no stop recorded)",
        },
    }
