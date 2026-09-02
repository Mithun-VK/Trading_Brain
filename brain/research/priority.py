"""Research priority scoring.

Turns a detected change into a comparable 0..1 score, so the queue can be
worked highest-first. Deterministic and explainable: every score carries the
`reasons` that produced it, and the weights are configuration, not magic
numbers buried in code.

The four components the spec calls for:
- importance        how hard the detection rule fired
- novelty           how long since we last researched this asset
- portfolio_impact  how much of the paper portfolio it represents
- watchlist_relevance  whether (and how widely) you're tracking it
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.research.change_detection import ChangeType, DetectedChange, _align
from models.paper_portfolio import PaperPortfolio, PaperPosition
from models.research_document import ResearchDocument
from models.watchlist import WatchlistItem


@dataclass(frozen=True)
class PriorityWeights:
    importance: float = 0.40
    novelty: float = 0.20
    portfolio_impact: float = 0.25
    watchlist_relevance: float = 0.15

    def normalized_total(self) -> float:
        return self.importance + self.novelty + self.portfolio_impact + self.watchlist_relevance


@dataclass(frozen=True)
class ResearchPriority:
    asset_id: int
    ticker: str
    change_type: ChangeType
    importance: float
    novelty: float
    portfolio_impact: float
    watchlist_relevance: float
    score: float
    reasons: list[str] = field(default_factory=list)


# Full novelty is reached at twice this many days without research.
_NOVELTY_SATURATION_DAYS = 30


class ResearchPriorityScorer:
    def __init__(self, weights: PriorityWeights | None = None) -> None:
        self.weights = weights or PriorityWeights()

    def score(
        self, session: Session, change: DetectedChange, now: dt.datetime
    ) -> ResearchPriority:
        reasons: list[str] = [change.summary]

        importance = change.magnitude
        novelty = self._novelty(session, change.asset_id, now, reasons)
        portfolio_impact = self._portfolio_impact(session, change.asset_id, reasons)
        watchlist_relevance = self._watchlist_relevance(session, change.asset_id, reasons)

        w = self.weights
        raw = (
            w.importance * importance
            + w.novelty * novelty
            + w.portfolio_impact * portfolio_impact
            + w.watchlist_relevance * watchlist_relevance
        )
        total_weight = w.normalized_total()
        score = raw / total_weight if total_weight else 0.0

        return ResearchPriority(
            asset_id=change.asset_id,
            ticker=change.ticker,
            change_type=change.change_type,
            importance=round(importance, 4),
            novelty=round(novelty, 4),
            portfolio_impact=round(portfolio_impact, 4),
            watchlist_relevance=round(watchlist_relevance, 4),
            score=round(score, 4),
            reasons=reasons,
        )

    # -- components -----------------------------------------------------------

    def _novelty(
        self, session: Session, asset_id: int, now: dt.datetime, reasons: list[str]
    ) -> float:
        latest = session.scalars(
            select(ResearchDocument)
            .where(ResearchDocument.asset_id == asset_id)
            .order_by(ResearchDocument.created_at.desc())
        ).first()

        if latest is None:
            reasons.append("no prior research on record")
            return 1.0

        days = (now - _align(latest.created_at, now)).days
        reasons.append(f"last researched {days}d ago")
        return min(1.0, days / (2 * _NOVELTY_SATURATION_DAYS))

    def _portfolio_impact(self, session: Session, asset_id: int, reasons: list[str]) -> float:
        """Largest share of any paper portfolio's equity this asset represents.

        Uses cost basis, not market value: this is a *triage* signal about
        how much is at stake, and it must not silently depend on whether a
        current price happens to be available.
        """
        positions = list(
            session.scalars(
                select(PaperPosition).where(
                    PaperPosition.asset_id == asset_id, PaperPosition.quantity > 0
                )
            ).all()
        )
        if not positions:
            return 0.0

        best = 0.0
        for position in positions:
            portfolio = session.get(PaperPortfolio, position.portfolio_id)
            if portfolio is None:
                continue
            cost_basis = float(position.quantity) * float(position.average_cost)
            denominator = float(portfolio.initial_cash)
            if denominator <= 0:
                continue
            best = max(best, min(1.0, cost_basis / denominator))

        if best > 0:
            reasons.append(f"held in a paper portfolio (~{best:.0%} of initial equity)")
        return best

    def _watchlist_relevance(
        self, session: Session, asset_id: int, reasons: list[str]
    ) -> float:
        count = len(
            list(
                session.scalars(
                    select(WatchlistItem).where(WatchlistItem.asset_id == asset_id)
                ).all()
            )
        )
        if count == 0:
            return 0.0
        reasons.append(f"on {count} watchlist{'s' if count > 1 else ''}")
        return min(1.0, 0.6 + 0.2 * (count - 1))
