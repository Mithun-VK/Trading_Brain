"""Learning-loop analyzers.

All deterministic: computed from stored outcomes, never inferred by Claude
(Rule 2). Each returns a block that carries its own sample size and caveat,
so a caller cannot present a number without the context that qualifies it.
"""

from __future__ import annotations

import datetime as dt
import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.learning.schemas import (
    AccuracyBlock,
    GroupPerformance,
    ResearchOutcomes,
    SignalAccuracy,
    StrategyPerformance,
    ThesisAccuracy,
)
from data.storage.price_repository import get_price_bars, normalize_ts
from models.asset import Asset
from models.company import Company
from models.research_document import ResearchDocument
from models.signal import Signal
from models.thesis import Thesis
from models.thesis_review_record import ThesisReviewRecord
from models.trade import Trade
from quant.performance.stats import expectancy, profit_factor, win_rate

# Signals that make a directional claim, and the sign that would confirm them.
DIRECTIONAL_SIGNALS: dict[str, int] = {
    "ACCUMULATE": +1,
    "REDUCE": -1,
    "EXIT_REVIEW": -1,
}
NON_DIRECTIONAL_SIGNALS = ("WATCH", "RESEARCH", "THESIS_REVIEW")

# Market-cap buckets, in the asset's own currency.
_CAP_BUCKETS = (
    (2e9, "small (<2B)"),
    (1e10, "mid (2B-10B)"),
    (float("inf"), "large (>10B)"),
)


def _align(value: dt.datetime, reference: dt.datetime) -> dt.datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value


def forward_return(
    session: Session, asset_id: int, from_time: dt.datetime, horizon_days: int
) -> float | None:
    """Return from the last close at/before `from_time` to the last close
    within `horizon_days` after it.

    Returns None when the horizon hasn't elapsed or prices are missing --
    an unresolved outcome, never a zero.
    """
    bars = get_price_bars(session, asset_id)
    if len(bars) < 2:
        return None

    anchor = normalize_ts(from_time)
    before = [b for b in bars if normalize_ts(b.ts) <= anchor]
    if not before:
        return None
    start_price = float(before[-1].close)
    if start_price <= 0:
        return None

    deadline = anchor + dt.timedelta(days=horizon_days)
    window = [b for b in bars if anchor < normalize_ts(b.ts) <= deadline]
    if not window:
        return None

    return round(float(window[-1].close) / start_price - 1, 6)


# -- thesis -------------------------------------------------------------------


def thesis_accuracy(
    session: Session, period_start: dt.date, period_end: dt.date
) -> ThesisAccuracy:
    result = ThesisAccuracy()
    theses = list(session.scalars(select(Thesis)).all())
    result.total_theses = len(theses)

    for thesis in theses:
        assessment = thesis.current_assessment
        if assessment == "THESIS_STRENGTHENED":
            result.strengthened += 1
        elif assessment == "THESIS_WEAKENED":
            result.weakened += 1
        elif assessment == "THESIS_INVALIDATED":
            result.invalidated += 1
        elif assessment == "THESIS_INTACT":
            result.intact += 1

    records = list(
        session.scalars(
            select(ThesisReviewRecord).order_by(ThesisReviewRecord.reviewed_at.asc())
        ).all()
    )
    result.reviews_recorded = len(records)

    # Time to invalidation, measured from thesis creation to its FIRST
    # invalidating review -- later re-reviews must not restart the clock.
    seen_invalidated: set[int] = set()
    for record in records:
        if record.assessment != "THESIS_INVALIDATED" or record.thesis_id in seen_invalidated:
            continue
        seen_invalidated.add(record.thesis_id)
        # Distinct name: `thesis` above is the non-null loop variable.
        invalidated_thesis = session.get(Thesis, record.thesis_id)
        if invalidated_thesis is None or invalidated_thesis.created_at is None:
            continue
        reviewed = _align(record.reviewed_at, record.reviewed_at)
        created = _align(invalidated_thesis.created_at, reviewed)
        days = (reviewed - created).days
        if days >= 0:
            result.days_to_invalidation.append(days)

    return result


# -- signals ------------------------------------------------------------------


def signal_accuracy(
    session: Session,
    period_start: dt.date,
    period_end: dt.date,
    horizon_days: int = 30,
    false_negative_threshold: float = -0.15,
) -> SignalAccuracy:
    result = SignalAccuracy(
        horizon_days=horizon_days,
        false_negative_threshold=false_negative_threshold,
        excluded_categories=list(NON_DIRECTIONAL_SIGNALS),
    )

    start = dt.datetime.combine(period_start, dt.time.min)
    end = dt.datetime.combine(period_end, dt.time.max)

    signals = list(
        session.scalars(
            select(Signal)
            .where(Signal.category.is_not(None))
            .order_by(Signal.generated_at.asc())
        ).all()
    )
    in_period = [
        s for s in signals if start <= normalize_ts(s.generated_at) <= end
    ]

    warned_assets: set[int] = set()

    for signal in in_period:
        category = signal.category or ""
        expected = DIRECTIONAL_SIGNALS.get(category)
        if expected is None:
            continue  # non-directional: excluded, not scored

        block = result.by_category.setdefault(category, AccuracyBlock(label=category))
        move = forward_return(session, signal.asset_id, signal.generated_at, horizon_days)

        if move is None:
            block.unresolved += 1
            result.overall.unresolved += 1
            continue

        if expected < 0:
            warned_assets.add(signal.asset_id)

        correct = (move > 0) if expected > 0 else (move < 0)
        if correct:
            block.correct += 1
            result.overall.correct += 1
        else:
            block.incorrect += 1
            result.overall.incorrect += 1

    result.false_negatives = _count_false_negatives(
        session, in_period, warned_assets, start, end, horizon_days, false_negative_threshold
    )
    return result


def _count_false_negatives(
    session: Session,
    signals: list[Signal],
    warned_assets: set[int],
    start: dt.datetime,
    end: dt.datetime,
    horizon_days: int,
    threshold: float,
) -> int:
    """Adverse moves nothing warned about.

    An asset that suffered a drop worse than `threshold` over the horizon
    without any REDUCE/EXIT_REVIEW in the period counts as a miss. Assets
    with no price history are skipped rather than counted either way.
    """
    misses = 0
    for asset in session.scalars(select(Asset)).all():
        if asset.id in warned_assets:
            continue
        move = forward_return(session, asset.id, start, horizon_days)
        if move is not None and move <= threshold:
            misses += 1
    return misses


# -- research -----------------------------------------------------------------


def research_outcomes(
    session: Session,
    period_start: dt.date,
    period_end: dt.date,
    horizon_days: int = 30,
) -> ResearchOutcomes:
    """Forward returns after research was published.

    Context only -- see `ResearchOutcomes.why_not_accuracy`.
    """
    result = ResearchOutcomes(horizon_days=horizon_days)
    start = dt.datetime.combine(period_start, dt.time.min)
    end = dt.datetime.combine(period_end, dt.time.max)

    documents = [
        d
        for d in session.scalars(select(ResearchDocument)).all()
        if d.asset_id is not None and start <= normalize_ts(d.created_at) <= end
    ]
    result.documents = len(documents)

    moves: list[float] = []
    for document in documents:
        assert document.asset_id is not None
        move = forward_return(session, document.asset_id, document.created_at, horizon_days)
        if move is None:
            continue
        moves.append(move)
        if move > 0:
            result.positive_outcomes += 1
        elif move < 0:
            result.negative_outcomes += 1

    result.resolved = len(moves)
    result.mean_forward_return = round(statistics.mean(moves), 6) if moves else None
    return result


# -- strategy -----------------------------------------------------------------


def _group_stats(label: str, r_multiples: list[float]) -> GroupPerformance:
    return GroupPerformance(
        label=label,
        trade_count=len(r_multiples),
        win_rate=round(win_rate(r_multiples), 4),
        expectancy_r=round(expectancy(r_multiples), 4),
        profit_factor=(
            round(profit_factor(r_multiples), 4)
            if profit_factor(r_multiples) != float("inf")
            else float("inf")
        ),
    )


def _cap_bucket(market_cap: int | None) -> str:
    if market_cap is None:
        return "unknown market cap"
    for ceiling, label in _CAP_BUCKETS:
        if market_cap < ceiling:
            return label
    return "unknown market cap"


def strategy_performance(
    session: Session, period_start: dt.date, period_end: dt.date
) -> StrategyPerformance:
    """Closed-trade performance grouped by regime, sector and market cap.

    Trades without an R-multiple (no stop was ever defined) are counted and
    excluded rather than scored with an invented risk figure.
    """
    result = StrategyPerformance()
    start = dt.datetime.combine(period_start, dt.time.min)
    end = dt.datetime.combine(period_end, dt.time.max)

    trades = [
        t
        for t in session.scalars(select(Trade).where(Trade.status == "closed")).all()
        if t.closed_at is not None and start <= normalize_ts(t.closed_at) <= end
    ]

    by_regime: dict[str, list[float]] = {}
    by_sector: dict[str, list[float]] = {}
    by_cap: dict[str, list[float]] = {}

    for trade in trades:
        if trade.r_multiple is None:
            result.trades_without_r_multiple += 1
            continue
        r = float(trade.r_multiple)
        result.scored_trades += 1

        by_regime.setdefault(trade.market_regime or "unknown regime", []).append(r)

        company = session.scalars(
            select(Company).where(Company.asset_id == trade.asset_id)
        ).first()
        by_sector.setdefault(
            (company.sector if company and company.sector else "unknown sector"), []
        ).append(r)
        by_cap.setdefault(
            _cap_bucket(company.market_cap if company else None), []
        ).append(r)

    result.by_regime = [_group_stats(k, v) for k, v in sorted(by_regime.items())]
    result.by_sector = [_group_stats(k, v) for k, v in sorted(by_sector.items())]
    result.by_market_cap = [_group_stats(k, v) for k, v in sorted(by_cap.items())]
    return result
