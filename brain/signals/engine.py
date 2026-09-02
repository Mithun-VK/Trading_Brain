"""SignalEngine: regime + quant + research + thesis -> attention signals.

Emits at most one signal per asset per run: rules are ordered by severity
and the first match wins, so a broken thesis is never buried under a
routine WATCH.

Nothing here can produce an execution instruction. The categories are a
closed enum, `GeneratedSignal` rejects execution-shaped names, and no code
path reaches a broker (Rules 7/8).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.signals.context import build_signal_context
from brain.signals.rules import RULES
from brain.signals.schemas import GeneratedSignal, SignalCategory
from config.logging import get_logger
from data.storage.signal_repository import save_signal
from data.storage.watchlist_repository import get_watched_asset_ids
from models.asset import Asset

logger = get_logger("signal_engine")


@dataclass
class SignalRunResult:
    assets_scanned: int = 0
    signals: list[GeneratedSignal] = field(default_factory=list)
    persisted: int = 0

    def by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for signal in self.signals:
            counts[str(signal.category)] = counts.get(str(signal.category), 0) + 1
        return counts


class SignalEngine:
    def generate_for_asset(
        self, session: Session, asset: Asset, now: dt.datetime
    ) -> GeneratedSignal | None:
        context = build_signal_context(session, asset, now)
        for rule in RULES:
            signal = rule(context)
            if signal is not None:
                return signal
        return None

    def run(
        self,
        session: Session,
        now: dt.datetime | None = None,
        assets: list[Asset] | None = None,
        persist: bool = True,
    ) -> SignalRunResult:
        now = now or dt.datetime.now(dt.UTC)
        assets = (
            assets
            if assets is not None
            else list(session.scalars(select(Asset).order_by(Asset.ticker)).all())
        )
        watched = get_watched_asset_ids(session)

        result = SignalRunResult(assets_scanned=len(assets))
        for asset in assets:
            context = build_signal_context(session, asset, now, watched_ids=watched)
            for rule in RULES:
                signal = rule(context)
                if signal is None:
                    continue
                result.signals.append(signal)
                if persist:
                    save_signal(session, signal, now)
                    result.persisted += 1
                break

        if persist:
            session.flush()

        logger.info(
            "signal_run_completed",
            operation="run",
            status="ok",
            assets=result.assets_scanned,
            signals=len(result.signals),
        )
        return result

    @staticmethod
    def categories() -> list[str]:
        """The complete, closed set of categories this engine can emit."""
        return [str(category) for category in SignalCategory]
