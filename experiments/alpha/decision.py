"""V5 — the decision engine.

No single metric threshold decides anything here. `evaluate()` takes a
`DecisionInputs` bundle covering out-of-sample performance, control
percentiles, effect size, concentration, regime consistency, robustness,
and contamination status, and returns a `DecisionStatus` **with reasons** --
never a bare letter grade.

**Contamination overrides everything else.** A `TEST_CONTAMINATED`
hypothesis is `E — INVALID_EXPERIMENT` regardless of how good its numbers
look, checked first and unconditionally. This is the one hard-coded rule in
the engine, and it is hard-coded on purpose: every other check below is a
judgment about evidence quality, and a contaminated test result has no
evidence quality to judge.

**Thresholds are named constants at module level, not literals buried in
`evaluate()`**, and `THRESHOLDS_VERSION` is bumped whenever any of them
changes -- so a report can always say which rule set produced its verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experiments.alpha.schema import DecisionStatus

THRESHOLDS_VERSION = "2026.09.1"

# A control percentile at or above this counts as "beat the control" for
# that metric -- the same bar V4.1 used throughout: beating the median is
# what half of all random draws also do.
EVIDENCE_PERCENTILE = 0.95

# Below this, an effect size is not economically distinguishable from noise
# even if it clears the percentile bar on a technicality.
MIN_ECONOMIC_EFFECT_SIZE = 0.3

# Robustness perturbations (cost/slippage/timing/universe/period) must
# survive at least this fraction to count as "robust" rather than "fragile."
MIN_ROBUSTNESS_SURVIVAL = 0.6

# Below this Sharpe retention with the top P&L contributor removed, a
# result is concentration-dependent regardless of anything else it shows --
# matches controls.COLLAPSE_RETENTION_THRESHOLD so the two modules agree.
MIN_CONCENTRATION_RETENTION = 0.5


@dataclass
class DecisionInputs:
    """Everything the engine needs, gathered by `evaluator.py` from the
    other stages. None of these fields is itself a verdict -- the engine
    is where they are combined into one."""

    test_contaminated: bool
    data_quality_ok: bool
    reproducible: bool

    test_period_percentile: float | None  # primary metric's percentile vs random control
    test_period_effect_size: float | None
    test_period_p_value: float | None

    concentration_dependent: bool
    concentration_retention: float | None

    regime_beaten_count: int  # regimes where the hypothesis cleared EVIDENCE_PERCENTILE
    regime_total_count: int

    robustness_survival_rate: float | None

    walk_forward_fold_win_rate: float | None  # share of folds where OOS beat the control

    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    reasons: list[str]
    thresholds_version: str = THRESHOLDS_VERSION

    def to_dict(self) -> dict:
        return {
            "status": str(self.status),
            "reasons": self.reasons,
            "thresholds_version": self.thresholds_version,
        }


def evaluate(inputs: DecisionInputs) -> Decision:
    reasons: list[str] = []

    # -- E: invalid experiment, checked first and unconditionally --------------
    if inputs.test_contaminated:
        return Decision(
            status=DecisionStatus.INVALID_EXPERIMENT,
            reasons=["test_period_contaminated"],
        )
    if not inputs.data_quality_ok:
        return Decision(
            status=DecisionStatus.INVALID_EXPERIMENT,
            reasons=["data_quality_check_failed"],
        )
    if not inputs.reproducible:
        return Decision(
            status=DecisionStatus.INVALID_EXPERIMENT,
            reasons=["reproducibility_check_failed"],
        )

    # -- gather the component judgments -----------------------------------------
    beats_control = (
        inputs.test_period_percentile is not None
        and inputs.test_period_percentile >= EVIDENCE_PERCENTILE
    )
    if beats_control:
        reasons.append(
            f"test_percentile_{inputs.test_period_percentile:.3f}_clears_{EVIDENCE_PERCENTILE:.2f}"
        )
    else:
        reasons.append("matched_random_control_not_beaten")

    economically_material = (
        inputs.test_period_effect_size is not None
        and abs(inputs.test_period_effect_size) >= MIN_ECONOMIC_EFFECT_SIZE
    )
    if not economically_material:
        reasons.append("effect_size_below_economic_materiality_floor")

    if inputs.concentration_dependent:
        reasons.append("concentration_dependent")
    elif (
        inputs.concentration_retention is not None
        and inputs.concentration_retention < MIN_CONCENTRATION_RETENTION
    ):
        reasons.append("concentration_retention_below_floor")

    regime_consistent = (
        inputs.regime_total_count > 0
        and inputs.regime_beaten_count >= max(1, inputs.regime_total_count // 2 + 1)
    )
    if inputs.regime_total_count > 0:
        reasons.append(
            f"regime_conditioned_control_beaten_in_{inputs.regime_beaten_count}"
            f"_of_{inputs.regime_total_count}"
        )
        if not regime_consistent:
            reasons.append("regime_conditioned_control_not_beaten")

    robust = (
        inputs.robustness_survival_rate is not None
        and inputs.robustness_survival_rate >= MIN_ROBUSTNESS_SURVIVAL
    )
    if not robust:
        reasons.append("robustness_survival_below_floor")

    fold_consistent = (
        inputs.walk_forward_fold_win_rate is not None
        and inputs.walk_forward_fold_win_rate >= 0.5
    )
    if inputs.walk_forward_fold_win_rate is not None and not fold_consistent:
        reasons.append("walk_forward_folds_inconsistent")

    # -- D: false edge -- clear negative evidence -------------------------------
    false_edge_signals = [
        not beats_control,
        inputs.concentration_dependent,
        inputs.regime_total_count > 0 and not regime_consistent,
    ]
    if sum(false_edge_signals) >= 2:
        return Decision(status=DecisionStatus.FALSE_EDGE, reasons=reasons)

    # -- A: supported -- every material check passes -----------------------------
    if (
        beats_control
        and economically_material
        and not inputs.concentration_dependent
        and (inputs.regime_total_count == 0 or regime_consistent)
        and robust
        and (inputs.walk_forward_fold_win_rate is None or fold_consistent)
    ):
        return Decision(status=DecisionStatus.SUPPORTED, reasons=reasons)

    # -- B: some evidence, not enough for all checks ------------------------------
    if beats_control or (economically_material and not inputs.concentration_dependent):
        return Decision(status=DecisionStatus.PROMISING_BUT_INSUFFICIENT, reasons=reasons)

    # -- C: no meaningful evidence either way -------------------------------------
    return Decision(status=DecisionStatus.NO_EVIDENCE, reasons=reasons)
