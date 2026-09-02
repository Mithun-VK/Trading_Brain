"""Learning-loop value types.

The hardest honesty problem in this phase is what "accuracy" may legitimately
mean. Three positions this module takes, all deliberate:

1. **Signals are scorable.** ACCUMULATE/REDUCE/EXIT_REVIEW carry an implied
   directional expectation, so a forward return can confirm or refute them.
   WATCH/RESEARCH/THESIS_REVIEW carry none and are excluded rather than
   scored against a direction they never claimed.

2. **Research is not scorable — yet.** A `ResearchAnalysis` contains no
   falsifiable directional prediction. Forward returns after a report are
   reported as *outcome context* and explicitly NOT called accuracy;
   inferring a direction the research never stated would be inventing the
   prediction we then grade (Rule 4). See `ResearchOutcomes.why_not_accuracy`.

3. **Nothing claims significance a sample can't support.** Every metric
   block carries its `sample_size`, and `is_significant` is False below
   MIN_SAMPLE_SIZE regardless of how good the numbers look.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

# Reuses the Phase 11 journal threshold so "too small to trust" means the
# same thing everywhere in TradingBrain.
from brain.review.schemas import MIN_SAMPLE_SIZE

__all__ = [
    "MIN_SAMPLE_SIZE",
    "ReviewKind",
    "AccuracyBlock",
    "ThesisAccuracy",
    "SignalAccuracy",
    "ResearchOutcomes",
    "GroupPerformance",
    "StrategyPerformance",
    "LearningReport",
]


class ReviewKind(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


@dataclass
class AccuracyBlock:
    """A scored outcome set. `sample_size` travels with the number, always."""

    label: str
    correct: int = 0
    incorrect: int = 0
    unresolved: int = 0

    @property
    def sample_size(self) -> int:
        return self.correct + self.incorrect

    @property
    def accuracy(self) -> float | None:
        """None when nothing has resolved -- not 0.0, which would read as
        'everything was wrong' rather than 'nothing is known yet'.
        """
        if self.sample_size == 0:
            return None
        return round(self.correct / self.sample_size, 4)

    @property
    def is_significant(self) -> bool:
        return self.sample_size >= MIN_SAMPLE_SIZE

    @property
    def caveat(self) -> str | None:
        if self.sample_size == 0:
            return "No resolved outcomes yet."
        if not self.is_significant:
            return (
                f"Sample size too small for statistical significance "
                f"(n={self.sample_size}, need {MIN_SAMPLE_SIZE})."
            )
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "unresolved": self.unresolved,
            "sample_size": self.sample_size,
            "accuracy": self.accuracy,
            "is_significant": self.is_significant,
            "caveat": self.caveat,
        }


@dataclass
class ThesisAccuracy:
    total_theses: int = 0
    strengthened: int = 0
    weakened: int = 0
    invalidated: int = 0
    intact: int = 0
    reviews_recorded: int = 0
    # Days from thesis creation to its first INVALIDATED review.
    days_to_invalidation: list[int] = field(default_factory=list)

    @property
    def median_days_to_invalidation(self) -> float | None:
        if not self.days_to_invalidation:
            return None
        ordered = sorted(self.days_to_invalidation)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[mid])
        return round((ordered[mid - 1] + ordered[mid]) / 2, 2)

    @property
    def invalidation_rate(self) -> float | None:
        if self.total_theses == 0:
            return None
        return round(self.invalidated / self.total_theses, 4)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_theses": self.total_theses,
            "strengthened": self.strengthened,
            "weakened": self.weakened,
            "invalidated": self.invalidated,
            "intact": self.intact,
            "reviews_recorded": self.reviews_recorded,
            "invalidation_rate": self.invalidation_rate,
            "median_days_to_invalidation": self.median_days_to_invalidation,
            "invalidation_samples": len(self.days_to_invalidation),
        }


@dataclass
class SignalAccuracy:
    horizon_days: int = 30
    by_category: dict[str, AccuracyBlock] = field(default_factory=dict)
    overall: AccuracyBlock = field(default_factory=lambda: AccuracyBlock("overall"))
    # Adverse moves that no REDUCE/EXIT_REVIEW warned about beforehand.
    false_negatives: int = 0
    false_negative_threshold: float = -0.15
    excluded_categories: list[str] = field(default_factory=list)

    @property
    def false_positives(self) -> int:
        """Signals that fired and were contradicted by the outcome."""
        return self.overall.incorrect

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_days": self.horizon_days,
            "overall": self.overall.to_dict(),
            "by_category": {k: v.to_dict() for k, v in sorted(self.by_category.items())},
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "false_negative_threshold": self.false_negative_threshold,
            "excluded_categories": self.excluded_categories,
            "note": (
                "Only directional categories are scored. "
                f"{', '.join(self.excluded_categories)} make no directional claim."
            ),
        }


@dataclass
class ResearchOutcomes:
    """Forward returns after research was published.

    Deliberately **not** an accuracy score -- see `why_not_accuracy`.
    """

    horizon_days: int = 30
    documents: int = 0
    resolved: int = 0
    mean_forward_return: float | None = None
    positive_outcomes: int = 0
    negative_outcomes: int = 0

    why_not_accuracy: str = (
        "ResearchAnalysis contains no falsifiable directional prediction, so "
        "these forward returns are context, not a score. Reading a direction "
        "into research that never claimed one would invent the prediction we "
        "then grade. To make this measurable, add an explicit directional "
        "expectation to the research schema."
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_days": self.horizon_days,
            "documents": self.documents,
            "resolved": self.resolved,
            "mean_forward_return": self.mean_forward_return,
            "positive_outcomes": self.positive_outcomes,
            "negative_outcomes": self.negative_outcomes,
            "is_accuracy_score": False,
            "why_not_accuracy": self.why_not_accuracy,
        }


@dataclass
class GroupPerformance:
    label: str
    trade_count: int = 0
    win_rate: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0

    @property
    def is_significant(self) -> bool:
        return self.trade_count >= MIN_SAMPLE_SIZE

    @property
    def caveat(self) -> str | None:
        if self.is_significant:
            return None
        return f"Sample size too small for statistical significance (n={self.trade_count})."

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "trade_count": self.trade_count,
            "win_rate": self.win_rate,
            "expectancy_r": self.expectancy_r,
            "profit_factor": self.profit_factor,
            "is_significant": self.is_significant,
            "caveat": self.caveat,
        }


@dataclass
class StrategyPerformance:
    by_regime: list[GroupPerformance] = field(default_factory=list)
    by_sector: list[GroupPerformance] = field(default_factory=list)
    by_market_cap: list[GroupPerformance] = field(default_factory=list)
    scored_trades: int = 0
    trades_without_r_multiple: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "scored_trades": self.scored_trades,
            "trades_without_r_multiple": self.trades_without_r_multiple,
            "by_regime": [g.to_dict() for g in self.by_regime],
            "by_sector": [g.to_dict() for g in self.by_sector],
            "by_market_cap": [g.to_dict() for g in self.by_market_cap],
        }


@dataclass
class LearningReport:
    kind: ReviewKind
    period_start: dt.date
    period_end: dt.date
    generated_at: dt.datetime
    thesis: ThesisAccuracy = field(default_factory=ThesisAccuracy)
    signals: SignalAccuracy = field(default_factory=SignalAccuracy)
    research: ResearchOutcomes = field(default_factory=ResearchOutcomes)
    strategy: StrategyPerformance = field(default_factory=StrategyPerformance)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": str(self.kind),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "thesis_accuracy": self.thesis.to_dict(),
            "signal_accuracy": self.signals.to_dict(),
            "research_outcomes": self.research.to_dict(),
            "strategy_performance": self.strategy.to_dict(),
        }
