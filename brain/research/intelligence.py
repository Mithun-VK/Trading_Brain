"""ResearchIntelligenceEngine: detect -> score -> queue.

This is the piece that makes TradingBrain continuous rather than
on-demand. It decides *what deserves attention* using deterministic rules
and stored data only; Claude is invoked afterwards, by the Research Agent,
to actually do the work on whatever surfaced here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.research.change_detection import (
    ChangeDetectionConfig,
    ChangeDetector,
    ChangeType,
    DetectedChange,
    detect_regime_change,
)
from brain.research.priority import PriorityWeights, ResearchPriority, ResearchPriorityScorer
from config.logging import get_logger
from data.storage.research_queue_repository import enqueue, get_queue
from data.storage.watchlist_repository import get_watched_asset_ids
from models.asset import Asset
from models.paper_portfolio import PaperPosition
from models.research_queue import ResearchQueueEntry

logger = get_logger("research_intelligence")


@dataclass
class IntelligenceRunResult:
    changes_detected: int = 0
    entries_created: int = 0
    entries_refreshed: int = 0
    assets_scanned: int = 0
    top: list[ResearchPriority] = field(default_factory=list)


class ResearchIntelligenceEngine:
    def __init__(
        self,
        detection_config: ChangeDetectionConfig | None = None,
        weights: PriorityWeights | None = None,
    ) -> None:
        self.detector = ChangeDetector(detection_config)
        self.scorer = ResearchPriorityScorer(weights)

    def scan(
        self,
        session: Session,
        now: dt.datetime | None = None,
        assets: list[Asset] | None = None,
    ) -> IntelligenceRunResult:
        now = now or dt.datetime.now(dt.UTC)
        assets = assets if assets is not None else list(
            session.scalars(select(Asset).order_by(Asset.ticker)).all()
        )

        result = IntelligenceRunResult(assets_scanned=len(assets))
        changes: list[DetectedChange] = []

        for asset in assets:
            changes.extend(self.detector.detect_for_asset(session, asset, now))

        changes.extend(self._regime_changes(session, assets, now))
        result.changes_detected = len(changes)

        priorities: list[ResearchPriority] = []
        for change in changes:
            priority = self.scorer.score(session, change, now)
            entry, created = enqueue(session, priority, change, now)
            priorities.append(priority)
            if created:
                result.entries_created += 1
            else:
                result.entries_refreshed += 1

        session.flush()
        result.top = sorted(priorities, key=lambda p: p.score, reverse=True)[:10]

        logger.info(
            "research_scan_completed",
            operation="scan",
            status="ok",
            assets=result.assets_scanned,
            changes=result.changes_detected,
            created=result.entries_created,
        )
        return result

    def pending_queue(
        self, session: Session, limit: int | None = None
    ) -> list[ResearchQueueEntry]:
        return get_queue(session, limit=limit)

    # -- internals ------------------------------------------------------------

    def _regime_changes(
        self, session: Session, assets: list[Asset], now: dt.datetime
    ) -> list[DetectedChange]:
        """Fan a market-level regime change out to *relevant* assets only.

        Applying it to every known asset would bury genuine per-asset
        signals under market-wide noise, so it lands on what you hold or
        watch.
        """
        market_change = detect_regime_change(session, now)
        if market_change is None:
            return []

        relevant_ids = get_watched_asset_ids(session)
        relevant_ids |= {
            position.asset_id
            for position in session.scalars(
                select(PaperPosition).where(PaperPosition.quantity > 0)
            ).all()
        }
        if not relevant_ids:
            return []

        return [
            DetectedChange(
                asset_id=asset.id,
                ticker=asset.ticker,
                change_type=ChangeType.REGIME_CHANGE,
                magnitude=market_change.magnitude,
                detected_at=now,
                detail=market_change.detail,
            )
            for asset in assets
            if asset.id in relevant_ids
        ]
