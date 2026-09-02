"""LearningEngine: measure what actually happened, then write it down.

Reports go to **both** stores, by design: PostgreSQL so the numbers stay
queryable and comparable over time, Obsidian so the narrative lives beside
the theses and trades it is judging (Rules 5/6).

Every rendered figure carries its caveat. A metric whose sample is too
small prints its warning inline rather than in a footnote nobody reads
(Rule 12).
"""

from __future__ import annotations

import calendar
import datetime as dt

from sqlalchemy.orm import Session

from brain.learning.metrics import (
    research_outcomes,
    signal_accuracy,
    strategy_performance,
    thesis_accuracy,
)
from brain.learning.schemas import GroupPerformance, LearningReport, ReviewKind
from config.logging import get_logger
from data.storage.learning_repository import save_learning_review
from integrations.obsidian.knowledge_store import KnowledgeStore

logger = get_logger("learning_engine")

REVIEW_FOLDER = "09 Reviews"

_DISCLAIMER = (
    "> Self-assessment computed from recorded outcomes. Past results do not "
    "predict future results, and figures marked with a sample-size warning are "
    "descriptive only -- they are not statistically significant (Rule 12)."
)


def period_bounds(kind: ReviewKind, as_of: dt.date) -> tuple[dt.date, dt.date]:
    """The completed period ending on or before `as_of`."""
    if kind is ReviewKind.MONTHLY:
        first_of_month = as_of.replace(day=1)
        end = first_of_month - dt.timedelta(days=1)
        start = end.replace(day=1)
        return start, end

    if kind is ReviewKind.QUARTERLY:
        current_quarter = (as_of.month - 1) // 3
        start_month = current_quarter * 3 + 1
        quarter_start = as_of.replace(month=start_month, day=1)
        end = quarter_start - dt.timedelta(days=1)
        prev_quarter = (end.month - 1) // 3
        start = end.replace(month=prev_quarter * 3 + 1, day=1)
        return start, end

    year = as_of.year - 1
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


class LearningEngine:
    def __init__(self, horizon_days: int = 30) -> None:
        self.horizon_days = horizon_days

    def build_report(
        self,
        session: Session,
        kind: ReviewKind = ReviewKind.MONTHLY,
        as_of: dt.date | None = None,
        now: dt.datetime | None = None,
    ) -> LearningReport:
        now = now or dt.datetime.now(dt.UTC)
        as_of = as_of or now.date()
        start, end = period_bounds(kind, as_of)

        return LearningReport(
            kind=kind,
            period_start=start,
            period_end=end,
            generated_at=now,
            thesis=thesis_accuracy(session, start, end),
            signals=signal_accuracy(session, start, end, horizon_days=self.horizon_days),
            research=research_outcomes(session, start, end, horizon_days=self.horizon_days),
            strategy=strategy_performance(session, start, end),
        )

    def render_markdown(self, report: LearningReport) -> str:
        lines = [
            "---",
            "type: learning_review",
            f"kind: {report.kind}",
            f"period_start: {report.period_start.isoformat()}",
            f"period_end: {report.period_end.isoformat()}",
            "---",
            "",
            f"# Learning Review — {report.kind.title()} "
            f"({report.period_start.isoformat()} to {report.period_end.isoformat()})",
            "",
            _DISCLAIMER,
            "",
            "## Thesis Accuracy",
        ]

        thesis = report.thesis
        lines += [
            f"- Theses tracked: {thesis.total_theses}",
            f"- Intact: {thesis.intact} · Strengthened: {thesis.strengthened} · "
            f"Weakened: {thesis.weakened} · Invalidated: {thesis.invalidated}",
            f"- Recorded reviews: {thesis.reviews_recorded}",
        ]
        if thesis.invalidation_rate is not None:
            lines.append(f"- Invalidation rate: {thesis.invalidation_rate:.1%}")
        if thesis.median_days_to_invalidation is not None:
            lines.append(
                f"- Median days to invalidation: "
                f"{thesis.median_days_to_invalidation:.0f} "
                f"(n={len(thesis.days_to_invalidation)})"
            )
        else:
            lines.append("- Median days to invalidation: no invalidations recorded yet.")

        lines += ["", f"## Signal Accuracy ({report.signals.horizon_days}-day horizon)"]
        overall = report.signals.overall
        if overall.accuracy is None:
            lines.append(f"- {overall.caveat}")
        else:
            lines.append(
                f"- Overall: {overall.accuracy:.1%} correct "
                f"({overall.correct}/{overall.sample_size})"
            )
            if overall.caveat:
                lines.append(f"  - ⚠ {overall.caveat}")
        lines.append(f"- Unresolved (horizon not yet elapsed): {overall.unresolved}")
        lines.append(f"- False positives: {report.signals.false_positives}")
        lines.append(
            f"- False negatives (adverse moves nothing warned about): "
            f"{report.signals.false_negatives}"
        )
        for name, block in sorted(report.signals.by_category.items()):
            accuracy = "n/a" if block.accuracy is None else f"{block.accuracy:.1%}"
            warning = f" ⚠ {block.caveat}" if block.caveat else ""
            lines.append(f"  - **{name}**: {accuracy} (n={block.sample_size}){warning}")
        lines.append(
            f"- Excluded (no directional claim): "
            f"{', '.join(report.signals.excluded_categories)}"
        )

        research = report.research
        lines += [
            "",
            f"## Research Outcomes ({research.horizon_days}-day horizon)",
            f"- Reports published: {research.documents} · resolved: {research.resolved}",
        ]
        if research.mean_forward_return is not None:
            lines.append(
                f"- Mean forward return after publication: "
                f"{research.mean_forward_return:.2%} "
                f"({research.positive_outcomes} up / {research.negative_outcomes} down)"
            )
        lines.append(f"- **Not an accuracy score.** {research.why_not_accuracy}")

        strategy = report.strategy
        lines += [
            "",
            "## Strategy Performance",
            f"- Scored trades: {strategy.scored_trades}",
        ]
        if strategy.trades_without_r_multiple:
            lines.append(
                f"- Excluded (no stop recorded, so no honest R-multiple): "
                f"{strategy.trades_without_r_multiple}"
            )
        for title, groups in (
            ("By Market Regime", strategy.by_regime),
            ("By Sector", strategy.by_sector),
            ("By Market Cap", strategy.by_market_cap),
        ):
            lines += ["", f"### {title}"]
            lines.extend(self._group_lines(groups))

        return "\n".join(lines)

    @staticmethod
    def _group_lines(groups: list[GroupPerformance]) -> list[str]:
        if not groups:
            return ["- No scored trades in this period."]
        lines = []
        for group in groups:
            warning = f" ⚠ {group.caveat}" if group.caveat else ""
            lines.append(
                f"- **{group.label}** (n={group.trade_count}): "
                f"win rate {group.win_rate:.1%}, "
                f"expectancy {group.expectancy_r:.2f}R{warning}"
            )
        return lines

    def publish(
        self,
        session: Session,
        report: LearningReport,
        knowledge_store: KnowledgeStore | None = None,
    ) -> str | None:
        """Store the report in PostgreSQL, and mirror it to Obsidian when a
        knowledge store is available. Returns the note path, if written.
        """
        markdown = self.render_markdown(report)
        note_path: str | None = None

        if knowledge_store is not None:
            note_path = (
                f"{REVIEW_FOLDER}/learning-{report.kind}-"
                f"{report.period_start.isoformat()}.md"
            )
            knowledge_store.write(note_path, markdown)

        save_learning_review(session, report, note_path=note_path)
        logger.info(
            "learning_review_published",
            operation="publish",
            status="ok",
            kind=str(report.kind),
            note_path=note_path,
        )
        return note_path

    def run(
        self,
        session: Session,
        kind: ReviewKind = ReviewKind.MONTHLY,
        as_of: dt.date | None = None,
        now: dt.datetime | None = None,
        knowledge_store: KnowledgeStore | None = None,
    ) -> LearningReport:
        report = self.build_report(session, kind=kind, as_of=as_of, now=now)
        self.publish(session, report, knowledge_store)
        return report
