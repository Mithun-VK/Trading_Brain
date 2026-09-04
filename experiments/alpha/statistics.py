"""V5 — statistical evaluation across multiple metrics, with research-breadth
tracking.

Two things this module refuses to let a caller skip:

**No metric is hard-coded as "the" alpha metric.** `evaluate_metrics` takes
whatever metric names the caller supplies and runs `montecarlo.compare` on
each -- Sharpe, CAGR, Sortino, win rate, whatever the evaluator's stage
needs. The decision engine (`decision.py`) is what decides which of these
matter and how; this module just measures.

**Multiple-testing exposure is recorded, not corrected away.** Per the
brief: "do not over-engineer statistical correction yet." `TestingLedger` is
a plain count of what was tried -- hypotheses, parameter variants, datasets,
universes, regime configurations, metrics inspected -- attached to every
report so a reader can judge "p < 0.05" in context, without this module
pretending to already know the right correction to apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experiments.montecarlo import NullComparison, compare, verdict


@dataclass(frozen=True)
class MetricEvaluation:
    """One metric's full statistical picture: the comparison itself, plus
    whether it counted toward the multiple-testing ledger as a *primary* or
    *secondary* inspection -- inspecting ten secondary metrics is a
    different epistemic act from testing ten independent hypotheses, and
    the ledger keeps them distinguishable."""

    comparison: NullComparison
    is_primary: bool

    def to_dict(self) -> dict:
        return {**self.comparison.to_dict(), "is_primary": self.is_primary}


def evaluate_metrics(
    observed: dict[str, float | None],
    null_draws: dict[str, list[float | None]],
    *,
    primary_metric: str,
) -> dict[str, MetricEvaluation]:
    """Compare every supplied metric against its null distribution.

    `primary_metric` must be named before this runs (it is the caller's
    job to fix it ahead of seeing results, same discipline as an ex-ante
    parameter) -- everything else in `observed` is reported as secondary
    evidence, informative but not itself sufficient for a GO.
    """
    if primary_metric not in observed:
        raise ValueError(f"primary_metric {primary_metric!r} is not in observed metrics.")

    out = {}
    for name, value in observed.items():
        comparison = compare(name, value, null_draws.get(name, []))
        out[name] = MetricEvaluation(comparison=comparison, is_primary=name == primary_metric)
    return out


def summarize(evaluations: dict[str, MetricEvaluation], *, primary_metric: str) -> dict:
    comparisons = {name: ev.comparison for name, ev in evaluations.items()}
    return verdict(comparisons, primary=primary_metric)


@dataclass
class TestingLedger:
    """What was actually tried, for the report's multiple-testing section.

    Every count defaults to 1 -- a single hypothesis, evaluated once, on one
    dataset, is one test of one thing, and the ledger should say that
    plainly rather than implying breadth that was not there.
    """

    hypothesis_count: int = 1
    parameter_variant_count: int = 1
    dataset_count: int = 1
    universe_count: int = 1
    regime_configuration_count: int = 1
    metrics_inspected: tuple[str, ...] = field(default_factory=tuple)
    primary_metric: str = ""
    selection_metric: str = ""
    contamination_status: str = "clean"

    def to_dict(self) -> dict:
        return {
            "tests_attempted": (
                self.hypothesis_count
                * self.parameter_variant_count
                * self.dataset_count
                * self.universe_count
                * self.regime_configuration_count
            ),
            "hypothesis_count": self.hypothesis_count,
            "parameter_variant_count": self.parameter_variant_count,
            "dataset_count": self.dataset_count,
            "universe_count": self.universe_count,
            "regime_configuration_count": self.regime_configuration_count,
            "primary_metric": self.primary_metric,
            "secondary_metrics": [m for m in self.metrics_inspected if m != self.primary_metric],
            "selection_metric": self.selection_metric,
            "contamination_status": self.contamination_status,
        }
