"""ReportingEngine: deterministic Markdown reports written into Obsidian.

Everything rendered here is read from stored records -- no Claude call
participates, so the same database state always produces byte-identical
Markdown. That makes reports diffable and reviewable.

Empty sections say so explicitly ("No X recorded") rather than being
omitted, because a missing section is ambiguous: it could mean nothing
happened, or that the query broke.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.learning.engine import LearningEngine
from brain.learning.schemas import ReviewKind
from brain.reporting.links import LinkResolver
from config.logging import get_logger
from data.storage.learning_repository import get_learning_reviews
from data.storage.portfolio_repository import list_portfolios
from data.storage.price_repository import get_close_series, normalize_ts
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.research_document import ResearchDocument
from models.research_queue import ResearchQueueEntry
from models.signal import Signal
from models.thesis import Thesis
from models.thesis_review_record import ThesisReviewRecord
from models.trade import Trade
from models.watchlist import WatchlistItem
from paper_trading.service import exposure_for, performance_for, valuation_for

logger = get_logger("reporting")

DAILY_FOLDER = "09 Reviews/Daily"
WEEKLY_FOLDER = "09 Reviews/Weekly"
MONTHLY_FOLDER = "09 Reviews/Monthly"

_DISCLAIMER = (
    "> Generated from recorded data. Descriptive only -- not financial advice "
    "and not a prediction (Rule 12)."
)


@dataclass
class Report:
    kind: str
    period_start: dt.date
    period_end: dt.date
    note_path: str
    markdown: str
    sections: dict[str, int] = field(default_factory=dict)


def _window(session: Session, start: dt.date, end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    return (
        dt.datetime.combine(start, dt.time.min),
        dt.datetime.combine(end, dt.time.max),
    )


def _in_window(value: dt.datetime, start: dt.datetime, end: dt.datetime) -> bool:
    stamp = normalize_ts(value)
    return start <= stamp <= end


class ReportingEngine:
    def __init__(self, knowledge_store: KnowledgeStore | None = None) -> None:
        self.knowledge_store = knowledge_store

    # -- public API -----------------------------------------------------------

    def daily(self, session: Session, as_of: dt.date | None = None) -> Report:
        as_of = as_of or dt.datetime.now(dt.UTC).date()
        return self._build(session, "daily", as_of, as_of, DAILY_FOLDER)

    def weekly(self, session: Session, as_of: dt.date | None = None) -> Report:
        as_of = as_of or dt.datetime.now(dt.UTC).date()
        start = as_of - dt.timedelta(days=6)
        return self._build(session, "weekly", start, as_of, WEEKLY_FOLDER)

    def monthly(self, session: Session, as_of: dt.date | None = None) -> Report:
        as_of = as_of or dt.datetime.now(dt.UTC).date()
        start = as_of.replace(day=1)
        return self._build(session, "monthly", start, as_of, MONTHLY_FOLDER)

    def publish(self, report: Report) -> str | None:
        """Write the report to Obsidian. Returns the path, or None when no
        knowledge store is configured -- the caller still has the Markdown.
        """
        if self.knowledge_store is None:
            return None
        self.knowledge_store.write(report.note_path, report.markdown)
        logger.info(
            "report_published",
            operation=report.kind,
            status="ok",
            note_path=report.note_path,
        )
        return report.note_path

    # -- construction ---------------------------------------------------------

    def _build(
        self, session: Session, kind: str, start: dt.date, end: dt.date, folder: str
    ) -> Report:
        links = LinkResolver(self.knowledge_store)
        window = _window(session, start, end)
        note_path = f"{folder}/{end.isoformat()}.md"

        lines = [
            "---",
            f"type: {kind}_report",
            f"period_start: {start.isoformat()}",
            f"period_end: {end.isoformat()}",
            "---",
            "",
            f"# {kind.title()} Report — {end.isoformat()}"
            + (f" (from {start.isoformat()})" if start != end else ""),
            "",
            _DISCLAIMER,
            "",
        ]
        counts: dict[str, int] = {}

        lines += self._regime_section(session)
        moves, move_lines = self._movers_section(session, links)
        counts["movers"] = moves
        lines += move_lines

        signals, signal_lines = self._signals_section(session, window, links)
        counts["signals"] = signals
        lines += signal_lines

        research, research_lines = self._research_section(session, window, links)
        counts["research"] = research
        lines += research_lines

        theses, thesis_lines = self._thesis_section(session, window, links)
        counts["thesis_changes"] = theses
        lines += thesis_lines

        lines += self._portfolio_section(session, links)

        if kind in ("weekly", "monthly"):
            trades, trade_lines = self._trade_section(session, window, links)
            counts["closed_trades"] = trades
            lines += trade_lines

        if kind == "monthly":
            lines += self._learning_section(session)
        elif kind == "weekly":
            lines += self._watchlist_section(session, window, links)

        return Report(
            kind=kind,
            period_start=start,
            period_end=end,
            note_path=note_path,
            markdown="\n".join(lines).rstrip() + "\n",
            sections=counts,
        )

    # -- sections -------------------------------------------------------------

    def _regime_section(self, session: Session) -> list[str]:
        observation = session.scalars(
            select(MarketRegimeObservation).order_by(
                MarketRegimeObservation.observed_at.desc()
            )
        ).first()
        lines = ["## Market Regime", ""]
        if observation is None:
            lines += ["No regime observation recorded yet.", ""]
            return lines
        lines += [
            f"- Trend: **{observation.regime}**",
            f"- Volatility: **{observation.volatility_regime}**",
            f"- Risk: **{observation.risk_regime}**",
            f"- Observed: {observation.observed_at.date().isoformat()} "
            f"(scope: {observation.scope})",
            "",
            "_Regimes are descriptive classifications of what already happened, "
            "not forecasts._",
            "",
        ]
        return lines

    def _movers_section(
        self, session: Session, links: LinkResolver, top: int = 5
    ) -> tuple[int, list[str]]:
        moves: list[tuple[str, float, str | None]] = []
        for asset in session.scalars(select(Asset).order_by(Asset.ticker)).all():
            closes = get_close_series(session, asset.id, limit=2)
            if len(closes) < 2 or closes[-2] == 0:
                continue
            moves.append((asset.ticker, closes[-1] / closes[-2] - 1, None))

        lines = ["## Major Moves", ""]
        if not moves:
            lines += ["No price history available to compute moves.", ""]
            return 0, lines

        moves.sort(key=lambda m: abs(m[1]), reverse=True)
        for ticker, move, _ in moves[:top]:
            arrow = "▲" if move > 0 else "▼"
            lines.append(f"- {arrow} {links.link_by_name(ticker)}: {move:+.2%}")
        lines.append("")
        return len(moves), lines

    def _signals_section(
        self, session: Session, window: tuple[dt.datetime, dt.datetime], links: LinkResolver
    ) -> tuple[int, list[str]]:
        start, end = window
        signals = [
            s
            for s in session.scalars(
                select(Signal)
                .where(Signal.category.is_not(None))
                .order_by(Signal.confidence.desc())
            ).all()
            if _in_window(s.generated_at, start, end)
        ]

        lines = ["## Signals", ""]
        if not signals:
            lines += ["No signals generated in this period.", ""]
            return 0, lines

        for signal in signals[:15]:
            asset = session.get(Asset, signal.asset_id)
            ticker = asset.ticker if asset else "?"
            confidence = (
                f"{float(signal.confidence):.2f}" if signal.confidence is not None else "n/a"
            )
            evidence_count = len(signal.evidence or [])
            lines.append(
                f"- **{signal.category}** {links.link_by_name(ticker)} "
                f"(confidence {confidence}, {evidence_count} evidence items)"
            )
            if signal.reasoning:
                lines.append(f"  - {signal.reasoning}")
        lines.append("")
        return len(signals), lines

    def _research_section(
        self, session: Session, window: tuple[dt.datetime, dt.datetime], links: LinkResolver
    ) -> tuple[int, list[str]]:
        start, end = window
        documents = [
            d
            for d in session.scalars(select(ResearchDocument)).all()
            if _in_window(d.created_at, start, end)
        ]
        queued = session.scalars(
            select(ResearchQueueEntry)
            .where(ResearchQueueEntry.status == "pending")
            .order_by(ResearchQueueEntry.score.desc())
            .limit(5)
        ).all()

        lines = ["## Research", ""]
        if documents:
            lines.append("**Published this period:**")
            for document in documents:
                label = document.title
                lines.append(f"- {links.link(document.obsidian_note_path, label)}")
        else:
            lines.append("No research published in this period.")
        lines.append("")

        lines.append("**Highest-priority queue:**")
        if queued:
            for entry in queued:
                lines.append(
                    f"- {links.link_by_name(entry.ticker)} — {entry.change_type} "
                    f"(priority {float(entry.score):.2f})"
                )
        else:
            lines.append("- Queue is empty.")
        lines.append("")
        return len(documents), lines

    def _thesis_section(
        self, session: Session, window: tuple[dt.datetime, dt.datetime], links: LinkResolver
    ) -> tuple[int, list[str]]:
        start, end = window
        records = [
            r
            for r in session.scalars(
                select(ThesisReviewRecord).order_by(ThesisReviewRecord.reviewed_at.desc())
            ).all()
            if _in_window(r.reviewed_at, start, end)
        ]

        lines = ["## Thesis Changes", ""]
        if not records:
            lines += ["No thesis reviews recorded in this period.", ""]
            return 0, lines

        for record in records:
            thesis = session.get(Thesis, record.thesis_id)
            label = thesis.title if thesis else f"thesis {record.thesis_id}"
            note_path = thesis.obsidian_note_path if thesis else None
            lines.append(
                f"- {links.link(note_path, label)}: "
                f"{record.previous_assessment} → **{record.assessment}**"
            )
        lines.append("")
        return len(records), lines

    def _portfolio_section(self, session: Session, links: LinkResolver) -> list[str]:
        portfolios = list_portfolios(session)
        lines = ["## Paper Portfolio", ""]
        if not portfolios:
            lines += ["No paper portfolio configured.", ""]
            return lines

        for portfolio in portfolios:
            valuation = valuation_for(session, portfolio)
            summary, daily_return, caveat = performance_for(session, portfolio)
            exposure = exposure_for(session, portfolio)

            lines += [
                f"### {portfolio.name}",
                f"- Equity: {valuation.total_equity:,.2f} {valuation.base_currency}",
                f"- Cash: {valuation.cash_balance:,.2f} "
                f"({exposure.cash_weight:.1%} of equity)",
                f"- Gross exposure: {valuation.exposure:.1%}",
                f"- Unrealized P&L: {valuation.unrealized_pnl:,.2f} · "
                f"Realized: {valuation.realized_pnl:,.2f}",
                f"- Total return: {valuation.total_return:+.2%}",
            ]
            if daily_return is not None:
                lines.append(f"- Latest daily return: {daily_return:+.2%}")
            if summary.snapshots >= 2:
                lines.append(f"- Max drawdown: {summary.max_drawdown:.2%}")
            if valuation.unpriced_positions:
                lines.append(
                    f"- ⚠ {valuation.unpriced_positions} position(s) had no price "
                    "available and are excluded from market value."
                )
            if caveat:
                lines.append(f"- ⚠ {caveat}")

            if valuation.positions:
                lines.append("")
                lines.append("| Position | Qty | Avg cost | Price | Weight |")
                lines.append("|---|---:|---:|---:|---:|")
                for position in valuation.positions:
                    price = (
                        f"{position.current_price:,.2f}"
                        if position.current_price is not None
                        else "—"
                    )
                    lines.append(
                        f"| {links.link_by_name(position.ticker)} "
                        f"| {position.quantity:,.2f} "
                        f"| {position.average_cost:,.2f} "
                        f"| {price} | {position.allocation:.1%} |"
                    )
            lines.append("")
        return lines

    def _trade_section(
        self, session: Session, window: tuple[dt.datetime, dt.datetime], links: LinkResolver
    ) -> tuple[int, list[str]]:
        start, end = window
        trades = [
            t
            for t in session.scalars(select(Trade).where(Trade.status == "closed")).all()
            if t.closed_at is not None and _in_window(t.closed_at, start, end)
        ]

        lines = ["## Closed Trades", ""]
        if not trades:
            lines += ["No trades closed in this period.", ""]
            return 0, lines

        for trade in trades:
            asset = session.get(Asset, trade.asset_id)
            ticker = asset.ticker if asset else "?"
            r_multiple = (
                f"{float(trade.r_multiple):+.2f}R" if trade.r_multiple is not None
                else "R unavailable (no stop recorded)"
            )
            lines.append(
                f"- {links.link(trade.obsidian_note_path, ticker)}: "
                f"{trade.result or 'unknown'} · {r_multiple}"
            )
        lines.append("")
        return len(trades), lines

    def _watchlist_section(
        self, session: Session, window: tuple[dt.datetime, dt.datetime], links: LinkResolver
    ) -> list[str]:
        start, end = window
        items = [
            i
            for i in session.scalars(select(WatchlistItem)).all()
            if _in_window(i.added_at, start, end)
        ]

        lines = ["## Watchlist Changes", ""]
        if not items:
            lines += ["No watchlist changes in this period.", ""]
            return lines
        for item in items:
            lines.append(
                f"- {links.link_by_name(item.asset.ticker)} added to "
                f"**{item.watchlist.name}**"
            )
        lines.append("")
        return lines

    def _learning_section(self, session: Session) -> list[str]:
        """Latest learning review, with its caveats preserved verbatim."""
        reviews = get_learning_reviews(session, limit=1)
        lines = ["## Learning", ""]
        if not reviews:
            lines += [
                "No learning review generated yet. Run the `learning_review` job.",
                "",
            ]
            return lines

        metrics = dict(reviews[0].metrics or {})
        signal_overall = metrics.get("signal_accuracy", {}).get("overall", {})
        thesis_block = metrics.get("thesis_accuracy", {})
        research_block = metrics.get("research_outcomes", {})

        accuracy = signal_overall.get("accuracy")
        lines.append(
            "- Signal accuracy: "
            + (
                f"{accuracy:.1%} (n={signal_overall.get('sample_size', 0)})"
                if accuracy is not None
                else "no resolved outcomes yet"
            )
        )
        if signal_overall.get("caveat"):
            lines.append(f"  - ⚠ {signal_overall['caveat']}")
        lines.append(
            f"- Theses tracked: {thesis_block.get('total_theses', 0)} · "
            f"invalidated: {thesis_block.get('invalidated', 0)}"
        )
        median_days = thesis_block.get("median_days_to_invalidation")
        lines.append(
            "- Median days to invalidation: "
            + (f"{median_days:.0f}" if median_days is not None else "none recorded")
        )
        lines.append(
            f"- Research outcomes are **not** an accuracy score: "
            f"{research_block.get('why_not_accuracy', 'no falsifiable prediction is made')}"
        )
        review_path = reviews[0].obsidian_note_path
        if review_path:
            resolver = LinkResolver(self.knowledge_store)
            lines.append(f"- Full review: {resolver.link(review_path, 'learning review')}")
        lines.append("")
        return lines


def generate_and_publish(
    session: Session,
    kind: str,
    knowledge_store: KnowledgeStore | None = None,
    as_of: dt.date | None = None,
) -> Report:
    engine = ReportingEngine(knowledge_store)
    builder = {"daily": engine.daily, "weekly": engine.weekly, "monthly": engine.monthly}
    if kind not in builder:
        raise ValueError(f"Unknown report kind {kind!r}")
    report = builder[kind](session, as_of)
    engine.publish(report)
    return report


def ensure_monthly_learning_review(
    session: Session, as_of: dt.date | None = None
) -> None:
    """Make sure a learning review exists before a monthly report cites it."""
    LearningEngine().run(session, kind=ReviewKind.MONTHLY, as_of=as_of)
