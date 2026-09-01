"""Company update: refresh profiles and fundamental metrics.

Slow-changing data, so this runs on a longer cadence than the price job.
Idempotent: profiles are updated in place (missing vendor fields never
blank out known values) and metrics are keyed on
(asset, metric, period, as_of_date).
"""

from __future__ import annotations

from sqlalchemy import select

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from config.logging import get_logger
from data.ingestion.errors import ProviderError
from data.storage.fundamentals_repository import upsert_company_profile, upsert_fundamentals
from models.asset import Asset

logger = get_logger("worker")


class CompanyUpdateJob(Job):
    name = "company_update"

    def run(self, context: JobContext) -> JobResult:
        if context.registry is None:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                error="No market data registry configured",
            )

        assets = list(
            context.session.scalars(
                select(Asset).where(Asset.asset_type == "equity").order_by(Asset.ticker)
            ).all()
        )
        if not assets:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                detail={"reason": "no equity assets registered"},
            )

        profiles_updated = 0
        metrics_written = 0
        failures: dict[str, str] = {}

        for asset in assets:
            # `execute` invokes the callable synchronously, so capturing the
            # loop variable directly is safe here.
            ticker = asset.ticker
            try:
                profile = context.registry.execute(
                    "get_company_profile",
                    lambda provider: provider.get_company_profile(ticker),
                )
                upsert_company_profile(context.session, asset, profile)
                profiles_updated += 1

                snapshot = context.registry.execute(
                    "get_fundamentals",
                    lambda provider: provider.get_fundamentals(ticker),
                )
                inserted, updated = upsert_fundamentals(context.session, asset.id, snapshot)
                metrics_written += inserted + updated
            except ProviderError as exc:
                failures[asset.ticker] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "company_update_failed",
                    operation=self.name,
                    status="error",
                    ticker=asset.ticker,
                )

        context.session.commit()
        return JobResult(
            job_name=self.name,
            status=JobStatus.PARTIAL if failures else JobStatus.SUCCESS,
            items_processed=profiles_updated,
            detail={
                "profiles_updated": profiles_updated,
                "metrics_written": metrics_written,
                "failures": failures,
            },
        )
