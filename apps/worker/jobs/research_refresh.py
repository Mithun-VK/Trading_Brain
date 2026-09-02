"""Research refresh: find what changed, score it, and queue it.

This is the job deferred from Phase 15 -- it's registered now that the
research queue it feeds actually exists.

Idempotent: `enqueue` refreshes an open entry for the same
(asset, change_type) rather than duplicating it, so re-running the job
updates priorities instead of flooding the queue.
"""

from __future__ import annotations

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from brain.research.intelligence import ResearchIntelligenceEngine


class ResearchRefreshJob(Job):
    name = "research_refresh"

    def __init__(self, engine: ResearchIntelligenceEngine | None = None) -> None:
        self.engine = engine or ResearchIntelligenceEngine()

    def run(self, context: JobContext) -> JobResult:
        result = self.engine.scan(context.session, now=context.now)
        context.session.commit()

        if result.assets_scanned == 0:
            return JobResult(
                job_name=self.name,
                status=JobStatus.SKIPPED,
                detail={"reason": "no assets registered"},
            )

        return JobResult(
            job_name=self.name,
            status=JobStatus.SUCCESS,
            items_processed=result.changes_detected,
            detail={
                "assets_scanned": result.assets_scanned,
                "changes_detected": result.changes_detected,
                "queue_entries_created": result.entries_created,
                "queue_entries_refreshed": result.entries_refreshed,
                "top": [
                    {"ticker": p.ticker, "change": str(p.change_type), "score": p.score}
                    for p in result.top[:5]
                ],
            },
        )
