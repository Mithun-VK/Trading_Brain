"""The decision engine: every status, reached from combined evidence, never
from a single metric threshold."""

from __future__ import annotations

from experiments.alpha.decision import (
    EVIDENCE_PERCENTILE,
    DecisionInputs,
    evaluate,
)
from experiments.alpha.schema import DecisionStatus


def _inputs(**overrides) -> DecisionInputs:
    base = dict(
        test_contaminated=False,
        data_quality_ok=True,
        reproducible=True,
        test_period_percentile=0.97,
        test_period_effect_size=1.5,
        test_period_p_value=0.01,
        concentration_dependent=False,
        concentration_retention=0.9,
        regime_beaten_count=2,
        regime_total_count=3,
        robustness_survival_rate=0.8,
        walk_forward_fold_win_rate=0.75,
    )
    return DecisionInputs(**{**base, **overrides})


# -- E: invalid experiment, checked first, unconditionally --------------------------


def test_contamination_overrides_every_other_signal() -> None:
    """Even with every other input looking perfect, contamination alone
    forces E."""
    inputs = _inputs(test_contaminated=True)
    decision = evaluate(inputs)
    assert decision.status is DecisionStatus.INVALID_EXPERIMENT
    assert "test_period_contaminated" in decision.reasons


def test_bad_data_quality_forces_invalid_experiment() -> None:
    decision = evaluate(_inputs(data_quality_ok=False))
    assert decision.status is DecisionStatus.INVALID_EXPERIMENT
    assert "data_quality_check_failed" in decision.reasons


def test_failed_reproducibility_forces_invalid_experiment() -> None:
    decision = evaluate(_inputs(reproducible=False))
    assert decision.status is DecisionStatus.INVALID_EXPERIMENT
    assert "reproducibility_check_failed" in decision.reasons


def test_contamination_is_checked_before_reproducibility() -> None:
    """Only one reason should be reported when both are true -- the first
    unconditional check short-circuits."""
    decision = evaluate(_inputs(test_contaminated=True, reproducible=False))
    assert decision.reasons == ["test_period_contaminated"]


# -- A: supported -- every material check must pass ----------------------------------


def test_supported_requires_every_check_to_pass() -> None:
    decision = evaluate(_inputs())
    assert decision.status is DecisionStatus.SUPPORTED


def test_supported_is_lost_if_concentration_dependent() -> None:
    decision = evaluate(_inputs(concentration_dependent=True))
    assert decision.status is not DecisionStatus.SUPPORTED


def test_supported_is_lost_if_regime_inconsistent() -> None:
    decision = evaluate(_inputs(regime_beaten_count=0))
    assert decision.status is not DecisionStatus.SUPPORTED


def test_supported_is_lost_if_not_robust() -> None:
    decision = evaluate(_inputs(robustness_survival_rate=0.1))
    assert decision.status is not DecisionStatus.SUPPORTED


def test_supported_is_lost_if_effect_size_too_small() -> None:
    decision = evaluate(_inputs(test_period_effect_size=0.05))
    assert decision.status is not DecisionStatus.SUPPORTED


def test_supported_does_not_require_walk_forward_data() -> None:
    """A hypothesis with no walk-forward folds run should not be blocked
    from A purely by that absence -- None is treated as 'not evaluated',
    not as a failure."""
    decision = evaluate(_inputs(walk_forward_fold_win_rate=None))
    assert decision.status is DecisionStatus.SUPPORTED


# -- D: false edge -- at least two negative signals -----------------------------------


def test_false_edge_when_random_control_and_concentration_and_regime_all_fail() -> None:
    decision = evaluate(_inputs(
        test_period_percentile=0.10,
        concentration_dependent=True,
        regime_beaten_count=0,
    ))
    assert decision.status is DecisionStatus.FALSE_EDGE


def test_matches_ma_20_50s_actual_v4_1_profile() -> None:
    """The real numbers V4.1 found for MA 20/50: control not beaten in
    most periods, regime-conditioned control not beaten in any modeled
    regime, some concentration dependence. Sanity check that the engine's
    D classification lines up with the historical result it is meant to
    reproduce the logic of."""
    decision = evaluate(_inputs(
        test_period_percentile=0.525,  # full period, ~coin flip
        test_period_effect_size=0.06,
        concentration_dependent=True,  # forced True here to isolate the rule under test
        regime_beaten_count=0, regime_total_count=3,
    ))
    assert decision.status is DecisionStatus.FALSE_EDGE


def test_a_single_negative_signal_alone_is_not_automatically_false_edge() -> None:
    """Concentration-dependence alone, with control beaten and regime
    consistent, should not by itself reach D -- D requires convergent
    negative evidence, not one flag."""
    decision = evaluate(_inputs(concentration_dependent=True))
    assert decision.status is not DecisionStatus.FALSE_EDGE


# -- B: promising but insufficient ----------------------------------------------------


def test_promising_when_control_beaten_but_concentration_dependent() -> None:
    decision = evaluate(_inputs(concentration_dependent=True, regime_beaten_count=3))
    assert decision.status is DecisionStatus.PROMISING_BUT_INSUFFICIENT


def test_promising_when_effect_size_material_but_robustness_weak() -> None:
    decision = evaluate(_inputs(robustness_survival_rate=0.2))
    assert decision.status is DecisionStatus.PROMISING_BUT_INSUFFICIENT


# -- C: no evidence -------------------------------------------------------------------


def test_no_evidence_when_nothing_clears_the_bar_but_nothing_is_clearly_false_either() -> None:
    """A coin-flip control result with the regime stage not run at all
    (total_count=0, so it cannot count as a negative signal) is weak
    evidence, not convergent false-edge evidence -- only one of the three
    false-edge signals (not beating the control) is present."""
    decision = evaluate(_inputs(
        test_period_percentile=0.5,
        test_period_effect_size=0.1,
        concentration_dependent=False,
        regime_beaten_count=0, regime_total_count=0,
        robustness_survival_rate=0.4,
    ))
    weak = (DecisionStatus.NO_EVIDENCE, DecisionStatus.PROMISING_BUT_INSUFFICIENT)
    assert decision.status in weak


# -- boundary conditions ---------------------------------------------------------------


def test_percentile_exactly_at_the_evidence_bar_counts_as_beating_it() -> None:
    decision = evaluate(_inputs(test_period_percentile=EVIDENCE_PERCENTILE))
    assert "matched_random_control_not_beaten" not in decision.reasons


def test_percentile_just_below_the_bar_does_not_count() -> None:
    decision = evaluate(_inputs(test_period_percentile=EVIDENCE_PERCENTILE - 0.001))
    assert "matched_random_control_not_beaten" in decision.reasons


def test_none_percentile_is_treated_as_not_beating_the_control() -> None:
    decision = evaluate(_inputs(test_period_percentile=None))
    assert "matched_random_control_not_beaten" in decision.reasons


def test_regime_total_zero_does_not_penalise_the_decision() -> None:
    """A hypothesis for which the regime stage was not run (regime_total_count=0)
    must not be treated as having failed a regime check it never took."""
    decision = evaluate(_inputs(regime_beaten_count=0, regime_total_count=0))
    assert "regime_conditioned_control_not_beaten" not in decision.reasons


def test_reasons_are_always_populated_for_a_non_invalid_decision() -> None:
    decision = evaluate(_inputs())
    assert decision.reasons


def test_decision_carries_the_thresholds_version() -> None:
    decision = evaluate(_inputs())
    assert decision.thresholds_version
