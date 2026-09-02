"""Learning review: measure recorded outcomes and write up the period.

Runs monthly. Quarterly and annual reviews use the same engine and are
generated on demand (or by a caller passing a different `kind`), since a
daily poll shouldn't decide what an "annual" boundary means.

Idempotent: reviews upsert by (kind, period_start), so re-running a month
refreshes it rather than accumulating duplicates.
"""

from __future__ import annotations

from apps.worker.jobs.base import Job, JobContext, JobResult, JobStatus
from brain.learning.engine import LearningEngine
from brain.learning.schemas import ReviewKind


class LearningReviewJob(Job):
    name = "learning_review"

    def __init__(
        self, kind: ReviewKind = ReviewKind.MONTHLY, engine: LearningEngine | None = None
    ) -> None:
        self.kind = kind
        self.engine = engine or LearningEngine()

    def run(self, context: JobContext) -> JobResult:
        report = self.engine.build_report(
            context.session, kind=self.kind, as_of=context.now.date(), now=context.now
        )
        note_path = self.engine.publish(
            context.session, report, knowledge_store=context.knowledge_store
        )
        context.session.commit()

        overall = report.signals.overall
        return JobResult(
            job_name=self.name,
            status=JobStatus.SUCCESS,
            items_processed=report.thesis.total_theses + overall.sample_size,
            detail={
                "kind": str(report.kind),
                "period": f"{report.period_start} to {report.period_end}",
                "note_path": note_path,
                "theses_tracked": report.thesis.total_theses,
                "signals_scored": overall.sample_size,
                "signal_accuracy": overall.accuracy,
                "signal_accuracy_significant": overall.is_significant,
                "scored_trades": report.strategy.scored_trades,
            },
        )
