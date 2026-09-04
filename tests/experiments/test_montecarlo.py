"""Monte Carlo null-distribution comparison.

Two properties carry this module. The p-value must never claim more
certainty than the sample size supports (the +1 correction), and an
undefined draw must be dropped and reported, never silently treated as
zero -- which would drag the null toward the middle and flatter whatever is
being tested against it.
"""

from __future__ import annotations

from experiments.montecarlo import compare, verdict


def test_the_p_value_floor_matches_the_plus_one_correction() -> None:
    """Beating every single draw must not report p=0 -- that claims more
    certainty than N draws can support. The floor is 1/(N+1)."""
    null = [0.5] * 100

    result = compare("sharpe", 1.0, null)

    assert result.p_value == round(1 / 101, 6)


def test_losing_to_every_draw_gives_a_p_value_near_one() -> None:
    null = [2.0] * 100

    result = compare("sharpe", 0.1, null)

    assert result.p_value == 1.0


def test_the_percentile_reflects_the_share_of_draws_beaten() -> None:
    null = list(range(100))  # 0..99

    result = compare("sharpe", 50, [float(x) for x in null])

    # 50 of the 100 draws (0..49) are strictly below the observed value.
    assert result.percentile == 0.50


def test_undefined_draws_are_dropped_and_reported_not_treated_as_zero() -> None:
    """Silently zeroing an undefined Sharpe would drag the null toward the
    middle and make the observed value look better than it is."""
    null = [1.0, None, 1.0, None, 1.0]

    result = compare("sharpe", 1.5, null)

    assert result.draws == 3
    assert "3 of 5" in result.note or "excluded" in result.note


def test_an_undefined_observed_value_cannot_be_placed() -> None:
    result = compare("sharpe", None, [1.0, 2.0, 3.0])

    assert result.percentile is None
    assert result.p_value is None
    assert "undefined" in result.note.lower()


def test_an_entirely_undefined_null_reports_no_comparison_is_possible() -> None:
    result = compare("sharpe", 1.0, [None, None, None])

    assert result.draws == 0
    assert result.null_mean is None
    assert "no comparison is possible" in result.note.lower()


def test_effect_size_is_standardised_by_the_null_spread() -> None:
    """A fixed distance from the mean means less when the null is wide and
    more when it is narrow -- effect size captures that, raw excess does
    not."""
    tight_null = [1.0, 1.0, 1.0, 1.0, 1.1, 0.9]
    wide_null = [1.0, 0.0, 2.0, -1.0, 3.0, -2.0]

    tight = compare("sharpe", 2.0, tight_null)
    wide = compare("sharpe", 2.0, wide_null)

    assert tight.effect_size is not None
    assert wide.effect_size is not None
    assert tight.effect_size > wide.effect_size


def test_a_single_draw_null_does_not_crash_on_stdev() -> None:
    result = compare("sharpe", 1.0, [0.5])

    assert result.null_stdev is None
    assert result.null_mean == 0.5


def test_significance_requires_the_005_threshold() -> None:
    strong = compare("sharpe", 10.0, [1.0] * 200)
    weak = compare("sharpe", 1.0, [1.0] * 200)

    assert strong.significant_at_05 is True
    assert weak.significant_at_05 is False


# -- percentile bounds -------------------------------------------------------------


def test_percentiles_are_monotonic() -> None:
    null = [float(x) for x in range(1000)]

    result = compare("sharpe", 500.0, null)

    assert result.null_p05 is not None
    assert result.null_p05 <= result.null_p25 <= result.null_median
    assert result.null_median <= result.null_p75 <= result.null_p95


# -- verdict summarisation ----------------------------------------------------------


def test_the_verdict_is_conservative_about_what_counts_as_signal() -> None:
    """Beating the median is what half of all random schedules also do --
    only clearing the 95th percentile counts as evidence."""
    comparisons = {
        "sharpe": compare("sharpe", 100.0, [1.0] * 200),  # beats everything
        "win_rate": compare("win_rate", 1.0, [1.0] * 200),  # ties the median
    }

    result = verdict(comparisons, primary="sharpe")

    assert "sharpe" in result["metrics_above_95th"]
    assert "win_rate" not in result["metrics_above_95th"]
    assert result["primary_metric"] == "sharpe"


def test_a_metric_below_the_null_median_is_flagged() -> None:
    comparisons = {"win_rate": compare("win_rate", 0.1, [0.9] * 200)}

    result = verdict(comparisons)

    assert "win_rate" in result["metrics_below_median"]
    assert "win_rate" not in result["metrics_above_median"]
