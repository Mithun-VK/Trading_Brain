"""Trading Journal Review Agent.

Pipeline: trades (PostgreSQL) -> deterministic performance statistics
(quant/performance) -> Claude pattern review -> Obsidian review note.

Statistics use R-multiples as the normalized PnL unit (trades don't store a
raw dollar PnL -- r_multiple is computed at close time and is the standard
way to compare trades of different position sizes). Any group with fewer
than MIN_SAMPLE_SIZE trades is flagged with a sample-size warning rather
than presented as if it were statistically meaningful.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy.orm import Session

from brain.review.schemas import (
    MIN_SAMPLE_SIZE,
    PATTERN_REVIEW_SCHEMA,
    GroupStats,
    JournalReview,
)
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.trade import Trade
from quant.performance.stats import (
    average_loser,
    average_winner,
    expectancy,
    profit_factor,
    win_rate,
)


def _strategy_label(trade: Trade) -> str:
    return trade.strategy.name if trade.strategy else "unassigned"


_DISCLAIMER = (
    "AI-generated pattern review over Claude-visible data only. Statistics with a "
    "sample-size warning are descriptive, not statistically significant (Rule 12)."
)


class TradeJournalReviewAgent:
    def __init__(
        self, session: Session, llm_provider: LLMProvider, knowledge_store: KnowledgeStore
    ) -> None:
        self._session = session
        self._llm_provider = llm_provider
        self._knowledge_store = knowledge_store

    def review(
        self,
        trades: list[Trade],
        period_start: dt.date | None = None,
        period_end: dt.date | None = None,
    ) -> JournalReview:
        closed = [t for t in trades if t.status == "closed" and t.r_multiple is not None]

        overall = self._group_stats("overall", closed)
        by_strategy = self._grouped(closed, key=_strategy_label)
        by_regime = self._grouped(closed, key=lambda t: t.market_regime or "unknown")

        prompt_context = self._build_prompt_context(overall, by_strategy, by_regime, closed)
        extracted = self._llm_provider.extract(
            prompt_context, schema=PATTERN_REVIEW_SCHEMA, max_tokens=2048
        )

        return JournalReview(
            period_start=period_start,
            period_end=period_end,
            overall=overall,
            by_strategy=by_strategy,
            by_regime=by_regime,
            generated_at=dt.datetime.now(dt.UTC),
            **extracted,
        )

    def _grouped(self, trades: list[Trade], key: Callable[[Trade], str]) -> list[GroupStats]:
        groups: dict[str, list[Trade]] = defaultdict(list)
        for trade in trades:
            groups[key(trade)].append(trade)
        return [self._group_stats(label, group) for label, group in sorted(groups.items())]

    def _group_stats(self, label: str, trades: list[Trade]) -> GroupStats:
        r_multiples = [float(t.r_multiple) for t in trades if t.r_multiple is not None]
        warning = None
        if len(r_multiples) < MIN_SAMPLE_SIZE:
            warning = f"Sample size too small for statistical significance (n={len(r_multiples)})"
        return GroupStats(
            label=label,
            trade_count=len(r_multiples),
            win_rate=win_rate(r_multiples),
            profit_factor=profit_factor(r_multiples),
            expectancy_r=expectancy(r_multiples),
            average_winner_r=average_winner(r_multiples),
            average_loser_r=average_loser(r_multiples),
            sample_size_warning=warning,
        )

    def _build_prompt_context(
        self,
        overall: GroupStats,
        by_strategy: list[GroupStats],
        by_regime: list[GroupStats],
        trades: list[Trade],
    ) -> str:
        lines = ["# Trading journal statistics (deterministic, computed before this review)", ""]
        lines.append(f"## Overall (n={overall.trade_count})")
        lines.append(str(overall.model_dump()))
        lines.append("")
        lines.append("## By strategy")
        for g in by_strategy:
            lines.append(f"- {g.label}: {g.model_dump()}")
        lines.append("")
        lines.append("## By market regime")
        for g in by_regime:
            lines.append(f"- {g.label}: {g.model_dump()}")
        lines.append("")
        lines.append("## Individual trades")
        for t in trades:
            lines.append(
                f"- {t.direction} {t.timeframe}, strategy={_strategy_label(t)}, "
                f"regime={t.market_regime}, result={t.result}, r_multiple={t.r_multiple}, "
                f"opened={t.opened_at.date().isoformat()}"
            )
        return "\n".join(lines)

    def render_markdown(self, review: JournalReview) -> str:
        lines = [
            "---",
            "type: trading_journal_review",
            f"generated: {review.generated_at.date().isoformat()}",
            f"confidence: {review.confidence}",
            "---",
            "",
            "# Trading Journal Review",
            "",
            _DISCLAIMER,
            "",
            f"## Overall ({review.overall.trade_count} trades)",
            f"- Win rate: {review.overall.win_rate:.1%}",
            f"- Expectancy: {review.overall.expectancy_r:.2f}R",
            f"- Profit factor: {review.overall.profit_factor:.2f}",
        ]
        if review.overall.sample_size_warning:
            lines.append(f"- ⚠ {review.overall.sample_size_warning}")
        lines.append("")

        grouped_sections = (
            ("By Strategy", review.by_strategy),
            ("By Market Regime", review.by_regime),
        )
        for title, groups in grouped_sections:
            lines.append(f"## {title}")
            for g in groups:
                warning = f" (⚠ {g.sample_size_warning})" if g.sample_size_warning else ""
                lines.append(
                    f"- **{g.label}** (n={g.trade_count}): win rate {g.win_rate:.1%}, "
                    f"expectancy {g.expectancy_r:.2f}R{warning}"
                )
            lines.append("")

        for section, items in (
            ("Patterns", review.patterns),
            ("Repeated Mistakes", review.repeated_mistakes),
            ("Rule Violations", review.rule_violations),
            ("Lessons", review.lessons),
        ):
            lines.append(f"## {section}")
            lines.extend(f"- {item}" for item in items)
            lines.append("")

        return "\n".join(lines)

    def publish(self, review: JournalReview, note_path: str | None = None) -> str:
        path = note_path or f"09 Reviews/journal-{review.generated_at.date().isoformat()}.md"
        self._knowledge_store.write(path, self.render_markdown(review))
        return path
