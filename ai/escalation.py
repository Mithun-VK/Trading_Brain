"""Event-driven AI escalation.

The question this module answers is not "can we reason about this" but
**"would reasoning add anything?"** -- and the default answer is no.

TradingBrain already detects and scores changes deterministically
(`brain.research.change_detection`, `brain.research.intelligence`). That
machinery is the filter: this module decides which of its output is material
enough to be worth a language model, and at what tier.

Deliberately conservative. A routine scheduled scan, a new candle, a small
price move, or a marginal indicator change must never trigger a frontier
call -- and none of them do, because the gate requires a detected change
whose *type* is escalation-worthy and whose *score* clears a threshold.

Note the current system has zero automatic AI triggers: the research queue
is populated automatically but only ever processed by an explicit human
action. This module keeps that property. It classifies and recommends; it
does not call the gateway. Nothing here can spend money on its own.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

from ai.schemas import AITaskType, AITier, RiskClass
from brain.research.change_detection import ChangeType, DetectedChange
from config.logging import get_logger

logger = get_logger("ai")


class TriggerKind(StrEnum):
    """Events that can justify reasoning. A closed set: an event type not
    listed here can never escalate, which is what stops the trigger surface
    growing quietly."""

    EARNINGS_RELEASE = "earnings_release"
    MATERIAL_ANNOUNCEMENT = "material_announcement"
    REGIME_SHIFT = "regime_shift"
    THESIS_CONTRADICTION = "thesis_contradiction"
    FUNDAMENTAL_CHANGE = "fundamental_change"
    UNEXPECTED_RISK_EVENT = "unexpected_risk_event"
    RESEARCH_CONFLICT = "research_conflict"
    HIGH_CONFIDENCE_ANOMALY = "high_confidence_anomaly"


# Change types that are *never* on their own a reason to reason. A price move
# is a fact the quant layer already handles; asking a language model to
# comment on it buys nothing and costs money.
NON_ESCALATING = frozenset(
    {
        ChangeType.PRICE_SHOCK,
        ChangeType.LARGE_MOVE,
        ChangeType.STALE_RESEARCH,
    }
)

# Detected change -> trigger kind, for the types that do justify reasoning.
_TRIGGER_FOR: dict[ChangeType, TriggerKind] = {
    ChangeType.EARNINGS_RELEASE: TriggerKind.EARNINGS_RELEASE,
    ChangeType.REGIME_CHANGE: TriggerKind.REGIME_SHIFT,
    ChangeType.THESIS_VIOLATION: TriggerKind.THESIS_CONTRADICTION,
}

# Below this the change is real but not material enough to pay for reasoning.
MATERIALITY_THRESHOLD = 0.6

# A thesis contradiction is the one event where the consequence of missing it
# is high enough to justify a lower bar.
THESIS_MATERIALITY_THRESHOLD = 0.4


class EscalationOutcome(StrEnum):
    NO_ACTION = "no_action"
    DETERMINISTIC_ONLY = "deterministic_only"
    LOCAL = "local"
    FRONTIER = "frontier"
    FRONTIER_HIGH = "frontier_high"


@dataclass(frozen=True)
class AITrigger:
    """A decision about one detected change, with its reasoning recorded.

    `escalate` is the answer; `reason` is why. Both are kept so that a
    frontier call can always be justified after the fact, and -- just as
    importantly -- so that a *refusal* to escalate is visible rather than
    being an absence of evidence.
    """

    kind: TriggerKind | None
    outcome: EscalationOutcome
    reason: str
    ticker: str | None = None
    asset_id: int | None = None
    materiality: float = 0.0
    task_type: AITaskType | None = None
    risk: RiskClass = RiskClass.MEDIUM
    detected_at: dt.datetime | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def escalate(self) -> bool:
        return self.outcome in {
            EscalationOutcome.LOCAL,
            EscalationOutcome.FRONTIER,
            EscalationOutcome.FRONTIER_HIGH,
        }

    @property
    def tier(self) -> AITier | None:
        return {
            EscalationOutcome.LOCAL: AITier.LOCAL,
            EscalationOutcome.FRONTIER: AITier.FRONTIER,
            EscalationOutcome.FRONTIER_HIGH: AITier.FRONTIER_HIGH,
        }.get(self.outcome)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": str(self.kind) if self.kind else None,
            "outcome": str(self.outcome),
            "reason": self.reason,
            "ticker": self.ticker,
            "materiality": self.materiality,
            "escalate": self.escalate,
            "task_type": str(self.task_type) if self.task_type else None,
        }


def evaluate(change: DetectedChange, *, has_contradictions: bool = False) -> AITrigger:
    """Decide whether one detected change justifies reasoning.

    The order of checks matters: the cheapest refusal comes first, and the
    default at every stage is not to escalate.
    """
    # 1. Is this the kind of event reasoning helps with at all?
    if change.change_type in NON_ESCALATING:
        return AITrigger(
            kind=None,
            outcome=EscalationOutcome.DETERMINISTIC_ONLY,
            reason=(
                f"{change.change_type} is a quantitative fact the deterministic "
                "layer already handles. A language model adds nothing here."
            ),
            ticker=change.ticker,
            asset_id=change.asset_id,
            materiality=change.magnitude,
            detected_at=change.detected_at,
        )

    kind = _TRIGGER_FOR.get(change.change_type)
    if kind is None:
        return AITrigger(
            kind=None,
            outcome=EscalationOutcome.NO_ACTION,
            reason=f"No escalation policy for change type {change.change_type}.",
            ticker=change.ticker,
            asset_id=change.asset_id,
            materiality=change.magnitude,
            detected_at=change.detected_at,
        )

    # 2. Is it material enough to pay for?
    threshold = (
        THESIS_MATERIALITY_THRESHOLD
        if kind is TriggerKind.THESIS_CONTRADICTION
        else MATERIALITY_THRESHOLD
    )
    if change.magnitude < threshold:
        return AITrigger(
            kind=kind,
            outcome=EscalationOutcome.NO_ACTION,
            reason=(
                f"Materiality {change.magnitude:.2f} is below the {threshold:.2f} "
                f"threshold for {kind}. Detected and queued, but not worth "
                "reasoning about yet."
            ),
            ticker=change.ticker,
            asset_id=change.asset_id,
            materiality=change.magnitude,
            detected_at=change.detected_at,
        )

    # 3. It is material. Which tier does it actually need?
    if kind is TriggerKind.THESIS_CONTRADICTION:
        return AITrigger(
            kind=kind,
            outcome=EscalationOutcome.FRONTIER_HIGH,
            reason=(
                "A thesis contradiction is the highest-consequence reasoning in "
                "this system: the conclusion may invalidate a held position."
            ),
            ticker=change.ticker,
            asset_id=change.asset_id,
            materiality=change.magnitude,
            task_type=AITaskType.THESIS_REVIEW,
            risk=RiskClass.HIGH,
            detected_at=change.detected_at,
            detail=dict(change.detail),
        )

    if has_contradictions:
        return AITrigger(
            kind=kind,
            outcome=EscalationOutcome.FRONTIER_HIGH,
            reason=(
                f"{kind} carries contradictory evidence; resolving a contradiction "
                "is a high-reasoning task."
            ),
            ticker=change.ticker,
            asset_id=change.asset_id,
            materiality=change.magnitude,
            task_type=AITaskType.RESEARCH_SYNTHESIS,
            risk=RiskClass.HIGH,
            detected_at=change.detected_at,
            detail=dict(change.detail),
        )

    return AITrigger(
        kind=kind,
        outcome=EscalationOutcome.FRONTIER,
        reason=(
            f"{kind} at materiality {change.magnitude:.2f} warrants synthesis "
            "across sources."
        ),
        ticker=change.ticker,
        asset_id=change.asset_id,
        materiality=change.magnitude,
        task_type=AITaskType.RESEARCH_SYNTHESIS,
        risk=RiskClass.MEDIUM,
        detected_at=change.detected_at,
        detail=dict(change.detail),
    )


def evaluate_all(changes: list[DetectedChange]) -> list[AITrigger]:
    """Classify a batch, newest and most material first.

    Returns every verdict, including the refusals. A caller that only wanted
    the escalations can filter, but the refusals are the more interesting
    half operationally -- they are the calls that were considered and not
    made.
    """
    triggers = [evaluate(change) for change in changes]
    escalating = sum(1 for t in triggers if t.escalate)
    if triggers:
        logger.info(
            "ai_escalation_evaluated",
            operation="evaluate_all",
            status="ok",
            considered=len(triggers),
            escalating=escalating,
            suppressed=len(triggers) - escalating,
        )
    return sorted(triggers, key=lambda t: t.materiality, reverse=True)
