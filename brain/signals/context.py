"""Assembles the four inputs a signal is allowed to reason over:
market regime, quant metrics, research state, and thesis state.

Everything here is read from stored data and computed deterministically.
No Claude call participates in producing a signal (Rule 2) -- Claude's
research *outputs* are an input, but the combination logic is code.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage.fundamentals_repository import get_latest_metrics
from data.storage.price_repository import get_close_series
from data.storage.watchlist_repository import get_watched_asset_ids
from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.paper_portfolio import PaperPosition
from models.research_document import ResearchDocument
from models.research_queue import ResearchQueueEntry
from models.thesis import Thesis
from quant.indicators.moving_average import sma
from quant.indicators.oscillators import rsi
from quant.indicators.returns import simple_returns, volatility

# Windows used for the quant view handed to the rules.
_MOMENTUM_WINDOW = 20
_VOLATILITY_WINDOW = 20


@dataclass
class QuantView:
    last_close: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    rsi_14: float | None = None
    momentum_20d: float | None = None
    volatility_20d: float | None = None

    @property
    def above_long_trend(self) -> bool | None:
        if self.last_close is None or self.sma_200 is None:
            return None
        return self.last_close > self.sma_200

    @property
    def positive_momentum(self) -> bool | None:
        if self.momentum_20d is None:
            return None
        return self.momentum_20d > 0


@dataclass
class SignalContext:
    asset: Asset
    ticker: str
    quant: QuantView
    regime: MarketRegimeObservation | None = None
    thesis: Thesis | None = None
    latest_research: ResearchDocument | None = None
    queue_entries: list[ResearchQueueEntry] = field(default_factory=list)
    position: PaperPosition | None = None
    is_watched: bool = False
    metrics: dict[str, float] = field(default_factory=dict)
    now: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def is_held(self) -> bool:
        return self.position is not None and float(self.position.quantity) > 0

    @property
    def pe_ratio(self) -> float | None:
        return self.metrics.get("pe_ratio")


def build_signal_context(
    session: Session,
    asset: Asset,
    now: dt.datetime,
    watched_ids: set[int] | None = None,
) -> SignalContext:
    closes = get_close_series(session, asset.id)
    watched = watched_ids if watched_ids is not None else get_watched_asset_ids(session)

    regime = session.scalars(
        select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
    ).first()

    thesis = session.scalars(
        select(Thesis).where(Thesis.asset_id == asset.id, Thesis.status == "active")
    ).first()

    latest_research = session.scalars(
        select(ResearchDocument)
        .where(ResearchDocument.asset_id == asset.id)
        .order_by(ResearchDocument.created_at.desc())
    ).first()

    queue_entries = list(
        session.scalars(
            select(ResearchQueueEntry)
            .where(
                ResearchQueueEntry.asset_id == asset.id,
                ResearchQueueEntry.status.in_(("pending", "in_progress")),
            )
            .order_by(ResearchQueueEntry.score.desc())
        ).all()
    )

    position = session.scalars(
        select(PaperPosition).where(
            PaperPosition.asset_id == asset.id, PaperPosition.quantity > 0
        )
    ).first()

    return SignalContext(
        asset=asset,
        ticker=asset.ticker,
        quant=_quant_view(closes),
        regime=regime,
        thesis=thesis,
        latest_research=latest_research,
        queue_entries=queue_entries,
        position=position,
        is_watched=asset.id in watched,
        metrics=get_latest_metrics(session, asset.id),
        now=now,
    )


def _quant_view(closes: list[float]) -> QuantView:
    if not closes:
        return QuantView()

    view = QuantView(last_close=closes[-1])
    if len(closes) >= 50:
        view.sma_50 = sma(closes, 50)[-1]
    if len(closes) >= 200:
        view.sma_200 = sma(closes, 200)[-1]
    if len(closes) >= 15:
        view.rsi_14 = rsi(closes, 14)[-1]
    if len(closes) > _MOMENTUM_WINDOW:
        past = closes[-(_MOMENTUM_WINDOW + 1)]
        view.momentum_20d = (closes[-1] / past - 1) if past else None
    if len(closes) > _VOLATILITY_WINDOW:
        view.volatility_20d = volatility(simple_returns(closes[-(_VOLATILITY_WINDOW + 1) :]))
    return view
