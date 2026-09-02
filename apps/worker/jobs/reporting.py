"""Report generation jobs.

Daily/weekly reports are written into Obsidian. A missing knowledge store
SKIPS rather than fails: reporting is an output channel, and its absence is
a configuration state, not an error.
"""

from __future__ import annotations

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from brain.reporting.engine import ReportingEngine
from integrations.obsidian.errors import ObsidianError


class _ReportJob(Job):
    kind = "daily"

    def run(self, context: JobContext) -> JobResult:
        if context.knowledge_store is None:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                detail={"reason": "no Obsidian knowledge store configured"},
            )

        engine = ReportingEngine(context.knowledge_store)
        builder = {
            "daily": engine.daily,
            "weekly": engine.weekly,
            "monthly": engine.monthly,
        }[self.kind]
        report = builder(context.session, context.now.date())

        try:
            note_path = engine.publish(report)
        except ObsidianError as exc:
            return JobResult(
                job_name=self.name,
                status=JobStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )

        return JobResult(
            job_name=self.name,
            status=JobStatus.SUCCESS,
            items_processed=sum(report.sections.values()),
            detail={"note_path": note_path, "sections": report.sections},
        )


class DailyReportJob(_ReportJob):
    name = "daily_report"
    kind = "daily"


class WeeklyReportJob(_ReportJob):
    name = "weekly_report"
    kind = "weekly"


class MonthlyReportJob(_ReportJob):
    name = "monthly_report"
    kind = "monthly"
