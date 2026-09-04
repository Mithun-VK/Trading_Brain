"""Robustness suite: cost/slippage multipliers, timing offsets, and the
hard structural rule that parameter sensitivity can never touch a
contaminated parameter."""

from __future__ import annotations

import datetime as dt

import pytest

from experiments.alpha.robustness import (
    cost_multiplier_configs,
    parameter_sensitivity_grid,
    slippage_multiplier_configs,
    survives,
    timing_perturbation_offsets,
)
from experiments.alpha.schema import ParameterRecord
from experiments.config import CostModel, ExperimentConfig, Period


def _config() -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="test", strategy="test_strategy", strategy_version="1.0",
        frozen_at_commit="abc123", costs=CostModel(commission_bps=5.0, slippage_bps=5.0),
        test=Period("test", dt.date(2020, 1, 1), dt.date(2021, 1, 1)),
    )


def _param(*, frozen: bool, selected_after: bool, value: float = 10.0) -> ParameterRecord:
    return ParameterRecord(
        name="p", value=value, source="lit", justification="x",
        frozen_before_test=frozen, selected_after_observation=selected_after,
    )


# -- cost / slippage multipliers -----------------------------------------------------


def test_cost_multipliers_scale_both_commission_and_slippage() -> None:
    base = _config()
    configs = cost_multiplier_configs(base, (1.0, 2.0, 3.0))
    labels = [label for label, _ in configs]
    assert labels == ["cost_1x", "cost_2x", "cost_3x"]

    _, doubled = configs[1]
    assert doubled.costs.commission_bps == base.costs.commission_bps * 2
    assert doubled.costs.slippage_bps == base.costs.slippage_bps * 2


def test_cost_multiplier_does_not_mutate_the_base_config() -> None:
    base = _config()
    cost_multiplier_configs(base, (2.0,))
    assert base.costs.commission_bps == 5.0


def test_slippage_multiplier_leaves_commission_untouched() -> None:
    base = _config()
    _, doubled = slippage_multiplier_configs(base, (2.0,))[0]
    assert doubled.costs.commission_bps == base.costs.commission_bps
    assert doubled.costs.slippage_bps == base.costs.slippage_bps * 2


def test_timing_offsets_are_the_specified_set() -> None:
    assert timing_perturbation_offsets() == (-1, 1, 2)


# -- survives() ------------------------------------------------------------------------


def test_a_perturbation_with_undefined_sharpe_does_not_survive() -> None:
    assert survives(1.0, None) is False


def test_a_negative_perturbed_sharpe_does_not_survive() -> None:
    assert survives(1.0, -0.1) is False


def test_a_perturbation_retaining_the_floor_fraction_survives() -> None:
    assert survives(1.0, 0.5) is True  # exactly the 0.5 floor


def test_a_perturbation_below_the_floor_fraction_does_not_survive() -> None:
    assert survives(1.0, 0.49) is False


def test_with_no_baseline_any_positive_perturbed_sharpe_survives() -> None:
    assert survives(None, 0.01) is True
    assert survives(0.0, 0.01) is True


# -- parameter sensitivity: the hard structural rule -----------------------------------


def test_a_frozen_parameter_produces_a_grid() -> None:
    params = (_param(frozen=True, selected_after=False, value=10.0),)
    grid = parameter_sensitivity_grid(params, step_fraction=0.2)
    assert grid["p"] == [8.0, 10.0, 12.0]


def test_a_contaminated_parameter_cannot_enter_the_grid_at_all() -> None:
    """The structural guard: sensitivity-testing an already-optimized
    parameter is parameter fishing wearing a robustness-check costume, and
    this function refuses to participate regardless of caller intent."""
    params = (_param(frozen=False, selected_after=True, value=10.0),)
    with pytest.raises(ValueError, match="frozen_before_test"):
        parameter_sensitivity_grid(params)


def test_a_parameter_not_marked_frozen_is_also_rejected() -> None:
    params = (_param(frozen=False, selected_after=False, value=10.0),)
    with pytest.raises(ValueError, match="frozen_before_test"):
        parameter_sensitivity_grid(params)


def test_one_contaminated_parameter_blocks_the_whole_grid() -> None:
    """Even if only one of several parameters is contaminated, the grid
    must not be built for any of them -- a mixed grid would let the
    contaminated parameter's neighbourhood be searched under cover of the
    clean ones' legitimate sensitivity check."""
    clean = _param(frozen=True, selected_after=False, value=5.0)
    dirty = ParameterRecord(
        name="q", value=99, source="grid search", justification="best on test",
        frozen_before_test=False, selected_after_observation=True,
    )
    with pytest.raises(ValueError):
        parameter_sensitivity_grid((clean, dirty))


def test_non_numeric_parameters_are_skipped_not_erroring() -> None:
    text_param = ParameterRecord(
        name="mode", value="long_only", source="design", justification="x",
        frozen_before_test=True, selected_after_observation=False,
    )
    grid = parameter_sensitivity_grid((text_param,))
    assert grid == {}


def test_integer_parameters_stay_integers_in_the_grid() -> None:
    int_param = _param(frozen=True, selected_after=False, value=126)
    # value is a float in the dataclass typing but int-valued; construct via int directly
    int_param = ParameterRecord(
        name="lookback", value=126, source="lit", justification="x",
        frozen_before_test=True, selected_after_observation=False,
    )
    grid = parameter_sensitivity_grid((int_param,), step_fraction=0.1)
    assert all(isinstance(v, int) for v in grid["lookback"])
