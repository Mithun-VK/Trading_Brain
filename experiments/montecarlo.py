"""Monte Carlo comparison against a null distribution.

Given one observed value and many draws from a matched random control, this
answers the only question that matters: could the observed result plausibly
have come from the control?

Everything here is deliberately non-parametric. The distribution of Sharpe
ratios across random entry schedules is not normal, and assuming it is would
produce a confident p-value from a wrong model.

The p-value is **one-sided** and computed with the standard +1 correction:

    p = (1 + #{draws >= observed}) / (1 + N)

The +1 matters. Without it, a strategy that beats all 5,000 draws reports
p = 0, which claims more certainty than 5,000 draws can support. With it,
the floor is 1/(N+1) -- the strongest statement the sample size permits.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class NullComparison:
    """One metric, compared against its null distribution."""

    metric: str
    observed: float | None
    draws: int
    null_mean: float | None = None
    null_median: float | None = None
    null_stdev: float | None = None
    null_p05: float | None = None
    null_p25: float | None = None
    null_p75: float | None = None
    null_p95: float | None = None
    percentile: float | None = None
    p_value: float | None = None
    excess_over_median: float | None = None
    effect_size: float | None = None  # (observed - null mean) / null stdev
    note: str = ""

    @property
    def significant_at_05(self) -> bool:
        return self.p_value is not None and self.p_value <= 0.05

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _percentile(ordered: list[float], q: float) -> float | None:
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def compare(
    metric: str, observed: float | None, null_values: list[float | None]
) -> NullComparison:
    """Place `observed` within the null distribution.

    Draws whose metric is undefined are dropped and the count is reported --
    silently treating an undefined Sharpe as zero would drag the null
    towards the middle and make the strategy look better than it is.
    """
    usable = [v for v in null_values if v is not None]
    dropped = len(null_values) - len(usable)
    result = NullComparison(metric=metric, observed=observed, draws=len(usable))

    if dropped:
        result.note = (
            f"{dropped} of {len(null_values)} draws had no defined {metric} "
            "and were excluded rather than counted as zero."
        )
    if not usable:
        result.note = f"No draw produced a defined {metric}; no comparison is possible."
        return result

    ordered = sorted(usable)
    result.null_mean = round(statistics.mean(ordered), 6)
    result.null_median = round(statistics.median(ordered), 6)
    result.null_stdev = round(statistics.stdev(ordered), 6) if len(ordered) > 1 else None
    result.null_p05 = _percentile(ordered, 0.05)
    result.null_p25 = _percentile(ordered, 0.25)
    result.null_p75 = _percentile(ordered, 0.75)
    result.null_p95 = _percentile(ordered, 0.95)

    if observed is None:
        result.note = (
            f"The observed {metric} is undefined, so it cannot be placed in "
            "the distribution."
        ).strip()
        return result

    at_or_above = sum(1 for v in ordered if v >= observed)
    below = sum(1 for v in ordered if v < observed)

    result.percentile = round(below / len(ordered), 6)
    result.p_value = round((1 + at_or_above) / (1 + len(ordered)), 6)
    result.excess_over_median = round(observed - result.null_median, 6)
    if result.null_stdev:
        result.effect_size = round((observed - result.null_mean) / result.null_stdev, 4)

    return result


def verdict(comparisons: dict[str, NullComparison], *, primary: str = "sharpe") -> dict:
    """Summarise a family of comparisons into a stated conclusion.

    Deliberately conservative. "Beat the median" is not evidence; a metric
    has to clear the 95th percentile of the null to count as signal, and the
    summary says which metrics did and did not.
    """
    beat_95 = [
        name for name, c in comparisons.items()
        if c.percentile is not None and c.percentile >= 0.95
    ]
    beat_median = [
        name for name, c in comparisons.items()
        if c.percentile is not None and c.percentile >= 0.50
    ]
    below_median = [
        name for name, c in comparisons.items()
        if c.percentile is not None and c.percentile < 0.50
    ]

    main = comparisons.get(primary)
    return {
        "primary_metric": primary,
        "primary_percentile": main.percentile if main else None,
        "primary_p_value": main.p_value if main else None,
        "primary_effect_size": main.effect_size if main else None,
        "metrics_above_95th": sorted(beat_95),
        "metrics_above_median": sorted(beat_median),
        "metrics_below_median": sorted(below_median),
        "significant_at_05": sorted(
            name for name, c in comparisons.items() if c.significant_at_05
        ),
    }
