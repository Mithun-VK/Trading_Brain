"""Deterministic change detection.

Claude decides *nothing* here. What is worth researching is computed from
stored data by explicit, thresholded rules (Rule 2); Claude is only invoked
later to actually perform the research on what these rules surfaced.

Every threshold lives in `ChangeDetectionConfig` -- nothing is hard-coded.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage.price_repository import get_close_series
from models.asset import Asset
from models.market_event import MarketEvent
from models.market_regime import MarketRegimeObservation
from models.research_document import ResearchDocument
from models.thesis import Thesis


class ChangeType(StrEnum):
    PRICE_SHOCK = "price_shock"
    LARGE_MOVE = "large_move"
    EARNINGS_RELEASE = "earnings_release"
    REGIME_CHANGE = "regime_change"
    THESIS_VIOLATION = "thesis_violation"
    STALE_RESEARCH = "stale_research"


@dataclass(frozen=True)
class ChangeDetectionConfig:
    price_shock_pct: float = 0.05
    large_move_pct: float = 0.15
    large_move_window: int = 20
    earnings_lookback_days: int = 7
    stale_research_days: int = 30
    thesis_stale_days: int = 45


@dataclass(frozen=True)
class DetectedChange:
    asset_id: int
    ticker: str
    change_type: ChangeType
    # 0..1 -- how strongly the rule fired, used as the `importance` component
    # of the priority score. Never a probability or a forecast.
    magnitude: float
    detected_at: dt.datetime
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return f"{self.change_type} on {self.ticker} (magnitude {self.magnitude:.2f})"


def _scaled(observed: float, threshold: float) -> float:
    """Normalize a threshold breach to 0..1.

    Hitting the threshold exactly scores 0.5; twice the threshold saturates
    at 1.0. Keeps magnitudes comparable across rule types.
    """
    if threshold <= 0:
        return 1.0
    return min(1.0, abs(observed) / (2 * threshold))


class ChangeDetector:
    def __init__(self, config: ChangeDetectionConfig | None = None) -> None:
        self.config = config or ChangeDetectionConfig()

    def detect_for_asset(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> list[DetectedChange]:
        changes: list[DetectedChange] = []
        changes.extend(self._price_changes(session, asset, now))
        changes.extend(self._earnings_changes(session, asset, now))
        changes.extend(self._thesis_changes(session, asset, now))
        stale = self._stale_research(session, asset, now)
        if stale is not None:
            changes.append(stale)
        return changes

    # -- individual rules -----------------------------------------------------

    def _price_changes(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> list[DetectedChange]:
        cfg = self.config
        window = cfg.large_move_window + 1
        closes = get_close_series(session, asset.id, limit=window)
        if len(closes) < 2:
            return []

        changes: list[DetectedChange] = []

        daily_return = closes[-1] / closes[-2] - 1
        if abs(daily_return) >= cfg.price_shock_pct:
            changes.append(
                DetectedChange(
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    change_type=ChangeType.PRICE_SHOCK,
                    magnitude=_scaled(daily_return, cfg.price_shock_pct),
                    detected_at=now,
                    detail={
                        "return": round(daily_return, 6),
                        "threshold": cfg.price_shock_pct,
                        "direction": "up" if daily_return > 0 else "down",
                    },
                )
            )

        if len(closes) >= window:
            window_return = closes[-1] / closes[0] - 1
            if abs(window_return) >= cfg.large_move_pct:
                changes.append(
                    DetectedChange(
                        asset_id=asset.id,
                        ticker=asset.ticker,
                        change_type=ChangeType.LARGE_MOVE,
                        magnitude=_scaled(window_return, cfg.large_move_pct),
                        detected_at=now,
                        detail={
                            "return": round(window_return, 6),
                            "window_days": cfg.large_move_window,
                            "threshold": cfg.large_move_pct,
                            "direction": "up" if window_return > 0 else "down",
                        },
                    )
                )

        return changes

    def _earnings_changes(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> list[DetectedChange]:
        cutoff = now - dt.timedelta(days=self.config.earnings_lookback_days)
        events = session.scalars(
            select(MarketEvent).where(
                MarketEvent.related_asset_id == asset.id,
                MarketEvent.event_type == "earnings",
                MarketEvent.occurred_at >= cutoff,
            )
        ).all()
        return [
            DetectedChange(
                asset_id=asset.id,
                ticker=asset.ticker,
                change_type=ChangeType.EARNINGS_RELEASE,
                magnitude=1.0,  # an earnings release always warrants a look
                detected_at=now,
                detail={"title": event.title, "occurred_at": event.occurred_at.isoformat()},
            )
            for event in events
        ]

    def _thesis_changes(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> list[DetectedChange]:
        thesis = session.scalars(
            select(Thesis).where(Thesis.asset_id == asset.id, Thesis.status == "active")
        ).first()
        if thesis is None:
            return []

        assessment = thesis.current_assessment
        if assessment == "THESIS_INVALIDATED":
            magnitude = 1.0
        elif assessment == "THESIS_WEAKENED":
            magnitude = 0.7
        else:
            magnitude = 0.0

        if magnitude > 0:
            return [
                DetectedChange(
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    change_type=ChangeType.THESIS_VIOLATION,
                    magnitude=magnitude,
                    detected_at=now,
                    detail={"assessment": assessment, "thesis_title": thesis.title},
                )
            ]

        # An intact thesis nobody has revisited in a long time is its own risk.
        last_reviewed = thesis.last_reviewed_at
        if last_reviewed is None:
            days = self.config.thesis_stale_days + 1
        else:
            days = (now - _align(last_reviewed, now)).days
        if days > self.config.thesis_stale_days:
            return [
                DetectedChange(
                    asset_id=asset.id,
                    ticker=asset.ticker,
                    change_type=ChangeType.THESIS_VIOLATION,
                    magnitude=_scaled(float(days), float(self.config.thesis_stale_days)),
                    detected_at=now,
                    detail={
                        "assessment": assessment,
                        "days_since_review": days,
                        "reason": "thesis not reviewed recently",
                    },
                )
            ]
        return []

    def _stale_research(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> DetectedChange | None:
        latest = session.scalars(
            select(ResearchDocument)
            .where(ResearchDocument.asset_id == asset.id)
            .order_by(ResearchDocument.created_at.desc())
        ).first()

        if latest is None:
            days = self.config.stale_research_days + 1
            reason = "never researched"
        else:
            days = (now - _align(latest.created_at, now)).days
            reason = "research is stale"

        if days <= self.config.stale_research_days:
            return None

        return DetectedChange(
            asset_id=asset.id,
            ticker=asset.ticker,
            change_type=ChangeType.STALE_RESEARCH,
            magnitude=_scaled(float(days), float(self.config.stale_research_days)),
            detected_at=now,
            detail={"days_since_research": days, "reason": reason},
        )


def detect_regime_change(session: Session, now: dt.datetime) -> DetectedChange | None:
    """Market-level: did the latest regime observation differ from the prior one?

    Returns a single market-wide change with no asset attached. The engine
    applies it only to assets you actually hold or watch -- fanning it out
    across every known asset would flood the queue with noise.
    """
    observations = list(
        session.scalars(
            select(MarketRegimeObservation)
            .order_by(MarketRegimeObservation.observed_at.desc())
            .limit(2)
        ).all()
    )
    if len(observations) < 2:
        return None

    latest, previous = observations[0], observations[1]
    trend_changed = latest.regime != previous.regime
    other_changed = (
        latest.volatility_regime != previous.volatility_regime
        or latest.risk_regime != previous.risk_regime
    )
    if not (trend_changed or other_changed):
        return None

    return DetectedChange(
        asset_id=0,
        ticker="",
        change_type=ChangeType.REGIME_CHANGE,
        magnitude=1.0 if trend_changed else 0.5,
        detected_at=now,
        detail={
            "from": {
                "trend": previous.regime,
                "volatility": previous.volatility_regime,
                "risk": previous.risk_regime,
            },
            "to": {
                "trend": latest.regime,
                "volatility": latest.volatility_regime,
                "risk": latest.risk_regime,
            },
            "trend_changed": trend_changed,
        },
    )


def _align(value: dt.datetime, reference: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; PostgreSQL returns aware ones."""
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
