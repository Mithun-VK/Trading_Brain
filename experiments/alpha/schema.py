"""V5 — the vocabulary every alpha experiment is written in.

Every type here exists to make a specific researcher mistake structurally
inconvenient:

- `HypothesisMetadata` cannot be constructed without an economic mechanism
  and falsification criteria, because "a strategy without an explicit
  mechanism cannot enter the research pipeline" is a rule this module
  enforces, not a rule that lives only in a document.
- `ParameterRecord` distinguishes a parameter chosen *before* looking at
  results from one chosen *after* -- `contaminated` is derived, not
  self-reported, from `frozen_before_test` and `selected_after_observation`
  being mutually exclusive claims about the same value.
- `ExperimentStatus` has no path from `FALSIFIED` back to `PROPOSED`. A
  falsified hypothesis is archived, not quietly retried under the same id
  (see `registry.py`).
- `DatasetContract` makes survivorship bias a field every report must
  render, not a footnote a report can omit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum


class ExperimentStatus(StrEnum):
    """Where a hypothesis is in the lifecycle. Transitions are enforced by
    `registry.py`, not by convention -- see `ALLOWED_TRANSITIONS` there."""

    PROPOSED = "proposed"
    IN_DEVELOPMENT = "in_development"
    VALIDATION = "validation"
    TEST_READY = "test_ready"
    TESTED = "tested"
    SURVIVED_FALSIFICATION = "survived_falsification"
    FALSIFIED = "falsified"
    TEST_CONTAMINATED = "test_contaminated"
    ARCHIVED = "archived"
    PAPER_TRADING_CANDIDATE = "paper_trading_candidate"


class DecisionStatus(StrEnum):
    """The decision engine's verdict. See `decision.py` for how each is
    reached -- never from a single metric threshold."""

    SUPPORTED = "A"
    PROMISING_BUT_INSUFFICIENT = "B"
    NO_EVIDENCE = "C"
    FALSE_EDGE = "D"
    INVALID_EXPERIMENT = "E"


class UniverseType(StrEnum):
    STATIC_CURRENT = "static_current"  # today's constituents, applied to the past
    POINT_IN_TIME = "point_in_time"  # constituents as they actually were on each date


class SurvivorshipRisk(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class DataQualityLevel(StrEnum):
    CONFIRMED = "confirmed"
    ASSUMED = "assumed"  # plausible given the vendor, not independently verified
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class DatasetContract:
    """What this run's data actually is, stated so a report can never
    imply institutional point-in-time data when it is a retail vendor feed.

    `experiments/data.py` already refuses to substitute synthetic data for
    a ticker that fails to fetch; this is the complementary declaration
    about what the *successfully fetched* data still is not.
    """

    provider: str
    universe_type: UniverseType
    survivorship_bias_risk: SurvivorshipRisk
    corporate_action_quality: DataQualityLevel
    delisted_security_coverage: DataQualityLevel
    timezone: str = "UTC"
    adjusted_prices: bool = True
    interval: str = "1d"
    note: str = ""

    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.universe_type is UniverseType.STATIC_CURRENT:
            out.append(
                "STATIC_CURRENT universe: constituents are today's, applied "
                "retroactively. Names that failed or were delisted before "
                "today are absent, biasing returns upward."
            )
        if self.survivorship_bias_risk in (SurvivorshipRisk.HIGH, SurvivorshipRisk.UNKNOWN):
            out.append(
                f"Survivorship bias risk is {self.survivorship_bias_risk}: treat "
                "absolute return figures as optimistic."
            )
        if self.delisted_security_coverage is not DataQualityLevel.CONFIRMED:
            out.append(
                f"Delisted-security coverage is {self.delisted_security_coverage}, "
                "not confirmed complete."
            )
        if self.corporate_action_quality is not DataQualityLevel.CONFIRMED:
            out.append(
                f"Corporate-action adjustment is {self.corporate_action_quality}, "
                "not independently confirmed."
            )
        return out


# The dataset contract for the Yahoo universe used throughout V1-V4.1 and
# this phase's example hypothesis. One shared constant, so every experiment
# using this data carries an identical, accurate declaration rather than a
# hand-copied one that can drift.
YAHOO_STATIC_UNIVERSE_CONTRACT = DatasetContract(
    provider="yahoo",
    universe_type=UniverseType.STATIC_CURRENT,
    survivorship_bias_risk=SurvivorshipRisk.HIGH,
    corporate_action_quality=DataQualityLevel.ASSUMED,
    delisted_security_coverage=DataQualityLevel.UNKNOWN,
    note=(
        "10-11 large-cap US names selected because they are large today, "
        "not a point-in-time institutional universe. See docs/RESEARCH_GOVERNANCE.md."
    ),
)


@dataclass(frozen=True)
class HypothesisMetadata:
    """The mechanism a strategy must state before it may be backtested.

    Every field is required and non-empty (`__post_init__`), because a
    hypothesis whose mechanism is missing is not a hypothesis that entered
    this pipeline honestly -- it is a signal someone is about to go looking
    for a reason for.
    """

    hypothesis_id: str
    hypothesis_name: str
    economic_mechanism: str
    expected_direction: str  # e.g. "long winners, short/flat losers"
    expected_holding_period: str  # e.g. "1-3 months"
    expected_market_behavior: str  # under what regime this should work/fail
    required_features: tuple[str, ...]
    known_failure_modes: tuple[str, ...]
    falsification_criteria: tuple[str, ...]
    researcher: str
    data_dependencies: tuple[str, ...]
    creation_timestamp: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )

    def __post_init__(self) -> None:
        required_text_fields = {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_name": self.hypothesis_name,
            "economic_mechanism": self.economic_mechanism,
            "expected_direction": self.expected_direction,
            "expected_holding_period": self.expected_holding_period,
            "expected_market_behavior": self.expected_market_behavior,
            "researcher": self.researcher,
        }
        for name, value in required_text_fields.items():
            if not value or not value.strip():
                raise ValueError(
                    f"HypothesisMetadata.{name} is required. A strategy without "
                    "an explicit mechanism cannot enter the research pipeline."
                )
        for name, seq in (
            ("required_features", self.required_features),
            ("known_failure_modes", self.known_failure_modes),
            ("falsification_criteria", self.falsification_criteria),
        ):
            if not seq:
                raise ValueError(
                    f"HypothesisMetadata.{name} must not be empty. Stating no "
                    "failure modes or no falsification criteria ahead of time "
                    "is exactly the omission this pipeline exists to prevent."
                )

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_name": self.hypothesis_name,
            "economic_mechanism": self.economic_mechanism,
            "expected_direction": self.expected_direction,
            "expected_holding_period": self.expected_holding_period,
            "expected_market_behavior": self.expected_market_behavior,
            "required_features": list(self.required_features),
            "known_failure_modes": list(self.known_failure_modes),
            "falsification_criteria": list(self.falsification_criteria),
            "researcher": self.researcher,
            "data_dependencies": list(self.data_dependencies),
            "creation_timestamp": self.creation_timestamp.isoformat(),
        }


@dataclass(frozen=True)
class ParameterRecord:
    """One parameter's value and where it came from.

    `contaminated` is not a field the caller sets -- it is derived from
    `frozen_before_test` and `selected_after_observation` being asserted
    together, which is a contradiction a caller could otherwise use to
    quietly launder an optimized parameter as an ex-ante one.
    """

    name: str
    value: float | int | str | bool
    source: str  # e.g. "prior literature", "economic reasoning", "grid search on validation"
    justification: str
    frozen_before_test: bool
    selected_after_observation: bool

    def __post_init__(self) -> None:
        if not self.justification.strip():
            raise ValueError(
                f"Parameter {self.name!r} has no justification. Every parameter "
                "must say why this value, not just what value."
            )
        if self.frozen_before_test and self.selected_after_observation:
            raise ValueError(
                f"Parameter {self.name!r} claims both frozen_before_test and "
                "selected_after_observation. A value cannot be both chosen "
                "before the test was seen and chosen after seeing it."
            )

    @property
    def contaminated(self) -> bool:
        """True if this value was selected after observing validation or
        test results -- it may not be presented as an ex-ante parameter."""
        return self.selected_after_observation or not self.frozen_before_test

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "source": self.source,
            "justification": self.justification,
            "frozen_before_test": self.frozen_before_test,
            "selected_after_observation": self.selected_after_observation,
            "contaminated": self.contaminated,
        }


@dataclass(frozen=True)
class ParameterSet:
    """All of a hypothesis's parameters, with the pipeline's one hard rule:
    a set containing any contaminated parameter can never be reported as a
    clean ex-ante result, regardless of what any individual stage found."""

    parameters: tuple[ParameterRecord, ...]

    @property
    def any_contaminated(self) -> bool:
        return any(p.contaminated for p in self.parameters)

    @property
    def contaminated_names(self) -> list[str]:
        return [p.name for p in self.parameters if p.contaminated]

    def as_values(self) -> dict[str, float | int | str | bool]:
        return {p.name: p.value for p in self.parameters}

    def to_dict(self) -> dict:
        return {
            "parameters": [p.to_dict() for p in self.parameters],
            "any_contaminated": self.any_contaminated,
            "contaminated_names": self.contaminated_names,
        }
