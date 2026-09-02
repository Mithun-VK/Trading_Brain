"""Signal types.

Every category here is an instruction to a **human's attention**, never to a
broker: look at this, research this, consider adding, consider trimming,
review this exit, revisit this thesis. There is deliberately no BUY, SELL,
or EXECUTE, and `SignalCategory` is a closed enum so one cannot be added by
accident (Rules 7/8).

Two invariants are enforced in code rather than trusted:
- a signal with no evidence cannot be constructed
- a category naming an execution action cannot be constructed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SignalCategory(StrEnum):
    WATCH = "WATCH"
    RESEARCH = "RESEARCH"
    ACCUMULATE = "ACCUMULATE"
    REDUCE = "REDUCE"
    EXIT_REVIEW = "EXIT_REVIEW"
    THESIS_REVIEW = "THESIS_REVIEW"


# Defense in depth. SignalCategory is closed, but this makes the intent
# explicit and gives the guard below something to check against if anyone
# later widens the type.
FORBIDDEN_CATEGORIES = frozenset(
    {"BUY", "SELL", "EXECUTE", "ORDER", "SUBMIT", "TRADE", "SHORT", "COVER"}
)


class SignalError(Exception):
    """A signal violated one of the engine's invariants."""


class EvidenceKind(StrEnum):
    REGIME = "regime"
    QUANT = "quant"
    THESIS = "thesis"
    RESEARCH = "research"
    POSITION = "position"
    VALUATION = "valuation"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    # Data we wanted but don't have. Recorded rather than ignored, and it
    # lowers confidence -- an unknown is not a quiet "fine".
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    detail: str
    stance: EvidenceStance = EvidenceStance.SUPPORTS
    value: float | str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": str(self.kind),
            "detail": self.detail,
            "stance": str(self.stance),
            "value": self.value,
        }


def compute_confidence(evidence: list[Evidence]) -> float:
    """Confidence from the evidence balance.

    supporting / (supporting + contradicting + 0.5 * unknown)

    Missing data counts at half weight against the signal: it neither
    confirms nor refutes, but it should stop a signal claiming certainty it
    hasn't earned (Rule 11).
    """
    supporting = sum(1 for e in evidence if e.stance is EvidenceStance.SUPPORTS)
    contradicting = sum(1 for e in evidence if e.stance is EvidenceStance.CONTRADICTS)
    unknown = sum(1 for e in evidence if e.stance is EvidenceStance.UNKNOWN)

    denominator = supporting + contradicting + 0.5 * unknown
    if denominator == 0:
        return 0.0
    return round(min(1.0, supporting / denominator), 4)


@dataclass(frozen=True)
class GeneratedSignal:
    asset_id: int
    ticker: str
    category: SignalCategory
    reasoning: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    rule: str = ""

    def __post_init__(self) -> None:
        if not self.evidence:
            raise SignalError(
                f"{self.category} signal for {self.ticker!r} has no evidence. "
                "Every signal must be traceable to what produced it (Rule 10)."
            )
        if str(self.category).upper() in FORBIDDEN_CATEGORIES:
            raise SignalError(
                f"{self.category!r} is an execution instruction. TradingBrain "
                "does not emit execution signals (Rules 7/8)."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise SignalError(f"confidence must be within 0..1, got {self.confidence}")

    @property
    def supporting(self) -> list[Evidence]:
        return [e for e in self.evidence if e.stance is EvidenceStance.SUPPORTS]

    @property
    def contradicting(self) -> list[Evidence]:
        return [e for e in self.evidence if e.stance is EvidenceStance.CONTRADICTS]

    def evidence_payload(self) -> list[dict[str, object]]:
        return [e.to_dict() for e in self.evidence]


def build_signal(
    asset_id: int,
    ticker: str,
    category: SignalCategory,
    reasoning: str,
    evidence: list[Evidence],
    rule: str,
) -> GeneratedSignal:
    """Construct a signal with confidence derived from its own evidence."""
    return GeneratedSignal(
        asset_id=asset_id,
        ticker=ticker,
        category=category,
        reasoning=reasoning,
        evidence=evidence,
        confidence=compute_confidence(evidence),
        rule=rule,
    )
