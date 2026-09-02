"""Portfolio update: snapshot every paper portfolio and refresh performance.

The last of the two jobs deferred from Phase 15; registered now that paper
portfolios and their snapshot history exist.

Idempotent: snapshots are unique per (portfolio, date), so re-running on the
same day updates the row rather than duplicating it.
"""

from __future__ import annotations

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from data.storage.portfolio_repository import list_portfolios
from paper_trading.tracking import performance, take_snapshot


class PortfolioUpdateJob(Job):
    name = "portfolio_update"

    def run(self, context: JobContext) -> JobResult:
        portfolios = list_portfolios(context.session)
        if not portfolios:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                detail={"reason": "no paper portfolios"},
            )

        as_of = context.now.date()
        summaries: dict[str, dict[str, float | bool]] = {}
        unpriced_total = 0

        for portfolio in portfolios:
            snapshot = take_snapshot(context.session, portfolio, as_of=as_of)
            unpriced_total += int(snapshot.unpriced_positions)
            summary = performance(context.session, portfolio)
            summaries[portfolio.name] = {
                "equity": summary.current_equity,
                "exposure": round(summary.current_exposure, 4),
                "total_return": summary.total_return,
                "max_drawdown": summary.max_drawdown,
                "snapshots": float(summary.snapshots),
                "fully_priced": summary.fully_priced,
            }

        context.session.commit()

        # A valuation taken while some holdings had no price is still
        # recorded, but the run reports PARTIAL so it isn't read as complete.
        status = JobStatus.PARTIAL if unpriced_total else JobStatus.SUCCESS
        return JobResult(
            job_name=self.name,
            status=status,
            items_processed=len(portfolios),
            detail={"portfolios": summaries, "unpriced_positions": unpriced_total},
        )
