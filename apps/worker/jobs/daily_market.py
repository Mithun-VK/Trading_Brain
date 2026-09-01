"""Daily market update: fetch prices incrementally, validate, persist, and
re-classify the market regime.

Idempotency comes from `upsert_price_bars` (natural-key dedupe) plus
incremental fetching anchored at the last stored bar -- running this job
twice in a day inserts nothing the second time.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from config.logging import get_logger
from data.ingestion.errors import ProviderError
from data.ingestion.schemas import Interval
from data.normalization.validation import validate_price_bars
from data.storage.price_repository import (
    get_close_series,
    get_latest_bar_ts,
    normalize_ts,
    upsert_price_bars,
)
from data.storage.regime_repository import save_regime_observation
from data.storage.validation_repository import save_validation_report
from models.asset import Asset
from quant.regime.detector import MarketRegimeDetector

logger = get_logger("worker")

# How far back to reach when an asset has no stored history at all.
_BACKFILL_DAYS = 400
# Re-fetch a small overlap so late vendor corrections are picked up; the
# upsert makes the overlap free.
_OVERLAP_DAYS = 5
# The regime detector needs 200 closes for a trend classification.
_REGIME_MIN_CLOSES = 200


class DailyMarketUpdateJob(Job):
    name = "daily_market_update"

    def __init__(
        self,
        interval: str = Interval.DAILY,
        regime_benchmark_ticker: str | None = None,
    ) -> None:
        self.interval = str(interval)
        self.regime_benchmark_ticker = regime_benchmark_ticker
        self.detector = MarketRegimeDetector()

    def run(self, context: JobContext) -> JobResult:
        if context.registry is None:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                error="No market data registry configured",
            )

        assets = list(context.session.scalars(select(Asset).order_by(Asset.ticker)).all())
        if not assets:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                detail={"reason": "no assets registered"},
            )

        updated: dict[str, int] = {}
        failures: dict[str, str] = {}

        for asset in assets:
            try:
                updated[asset.ticker] = self._update_asset(context, asset)
            except ProviderError as exc:
                # One bad symbol must not abort the whole market update.
                failures[asset.ticker] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "daily_update_symbol_failed",
                    operation=self.name,
                    status="error",
                    ticker=asset.ticker,
                )

        context.session.commit()
        regime = self._update_regime(context, assets)

        status = JobStatus.PARTIAL if failures else JobStatus.SUCCESS
        return JobResult(
            job_name=self.name,
            status=status,
            items_processed=len(updated),
            detail={
                "bars_inserted": sum(updated.values()),
                "per_ticker": updated,
                "failures": failures,
                "regime": regime,
            },
        )

    def _update_asset(self, context: JobContext, asset: Asset) -> int:
        assert context.registry is not None
        end = context.now.date()
        latest = get_latest_bar_ts(context.session, asset.id, self.interval)
        if latest is None:
            start = end - dt.timedelta(days=_BACKFILL_DAYS)
        else:
            start = normalize_ts(latest).date() - dt.timedelta(days=_OVERLAP_DAYS)

        bars = context.registry.execute(
            "get_historical_prices",
            lambda provider: provider.get_historical_prices(
                asset.ticker, start, end, self.interval
            ),
        )

        report = validate_price_bars(
            bars,
            ticker=asset.ticker,
            interval=self.interval,
            source=bars[0].source if bars else "unknown",
            now=context.now,
        )
        if report.issues:
            save_validation_report(context.session, report, asset_id=asset.id)

        result = upsert_price_bars(context.session, asset.id, report.valid_bars)
        return result.inserted

    def _update_regime(self, context: JobContext, assets: list[Asset]) -> dict[str, str] | None:
        """Classify the broad market from a benchmark asset's closes.

        Returns None (and stores nothing) when there isn't enough history --
        an UNKNOWN-everything observation would be noise, not information.
        """
        benchmark = self._resolve_benchmark(assets)
        if benchmark is None:
            return None

        closes = get_close_series(context.session, benchmark.id, self.interval)
        if len(closes) < _REGIME_MIN_CLOSES:
            return None

        observation = self.detector.detect(closes, observed_at=context.now)
        save_regime_observation(context.session, observation, scope=f"benchmark:{benchmark.ticker}")
        context.session.commit()
        return {
            "trend": str(observation.trend_regime),
            "volatility": str(observation.volatility_regime),
            "risk": str(observation.risk_regime),
            "benchmark": benchmark.ticker,
        }

    def _resolve_benchmark(self, assets: list[Asset]) -> Asset | None:
        if self.regime_benchmark_ticker:
            return next(
                (a for a in assets if a.ticker == self.regime_benchmark_ticker),
                None,
            )
        index = next((a for a in assets if a.asset_type == "index"), None)
        return index or (assets[0] if assets else None)
