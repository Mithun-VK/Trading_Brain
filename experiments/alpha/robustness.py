"""V5 — the robustness suite.

Every check here answers "does the hypothesis survive a reasonable
perturbation" -- never "which perturbation makes it look best." That
distinction is the whole point of this module, and it is enforced
structurally in one place: `parameter_sensitivity` only accepts parameters
already marked `frozen_before_test` (`schema.ParameterRecord`). A
contaminated parameter cannot be handed to this function at all, so there
is no path from "robustness check" to "parameter search" through this code.

Each perturbation reuses the same `experiments.runner.run` entry point V2-
V4.1 already use -- this module builds perturbed *configs*, never a second
backtest engine.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from experiments.alpha.schema import ParameterRecord
from experiments.config import ExperimentConfig
from experiments.metrics import PerformanceRecord


@dataclass(frozen=True)
class PerturbationResult:
    label: str
    metrics: PerformanceRecord
    survived: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "metrics": self.metrics.to_dict(),
            "survived": self.survived,
            "note": self.note,
        }


# A perturbed run "survives" if Sharpe stays positive and does not fall by
# more than this fraction of the baseline. Fixed before any hypothesis in
# this framework was evaluated.
SURVIVAL_SHARPE_FLOOR_FRACTION = 0.5


def survives(baseline_sharpe: float | None, perturbed_sharpe: float | None) -> bool:
    if perturbed_sharpe is None:
        return False
    if perturbed_sharpe <= 0:
        return False
    if baseline_sharpe is None or baseline_sharpe <= 0:
        return perturbed_sharpe > 0
    return perturbed_sharpe >= baseline_sharpe * SURVIVAL_SHARPE_FLOOR_FRACTION


def cost_multiplier_configs(
    base: ExperimentConfig, multipliers: tuple[float, ...] = (1.0, 2.0, 3.0)
) -> list[tuple[str, ExperimentConfig]]:
    """Baseline, 2x, and 3x commission+slippage -- a strategy whose edge
    does not survive a cost multiple that a real venue could plausibly
    charge was never economically viable, whatever its gross numbers say."""
    out = []
    for m in multipliers:
        costs = dataclasses.replace(
            base.costs,
            commission_bps=base.costs.commission_bps * m,
            slippage_bps=base.costs.slippage_bps * m,
        )
        out.append((f"cost_{m:g}x", dataclasses.replace(base, costs=costs)))
    return out


def slippage_multiplier_configs(
    base: ExperimentConfig, multipliers: tuple[float, ...] = (1.0, 2.0, 3.0)
) -> list[tuple[str, ExperimentConfig]]:
    """Slippage alone, held apart from commission -- a strategy can be
    insensitive to commission (low turnover) and highly sensitive to
    slippage (illiquid names, large size) or vice versa; conflating them
    into one 'costs' knob would hide which one actually matters."""
    out = []
    for m in multipliers:
        costs = dataclasses.replace(base.costs, slippage_bps=base.costs.slippage_bps * m)
        out.append((f"slippage_{m:g}x", dataclasses.replace(base, costs=costs)))
    return out


def timing_perturbation_offsets() -> tuple[int, ...]:
    """Bars to shift every entry by. A signal that only works at its exact
    computed entry bar and collapses one bar either side is fitting
    execution-day noise, not a real information edge."""
    return (-1, 1, 2)


def parameter_sensitivity_grid(
    parameters: tuple[ParameterRecord, ...], *, step_fraction: float = 0.2
) -> dict[str, list[float | int]]:
    """Nearby values for each numeric, ex-ante-frozen parameter.

    Refuses any parameter not marked `frozen_before_test` -- sensitivity
    testing a value chosen after seeing results is a parameter search
    wearing a robustness-check costume, and this function will not
    participate in that regardless of what the caller intended.
    """
    grid: dict[str, list[float | int]] = {}
    for p in parameters:
        if not p.frozen_before_test or p.selected_after_observation:
            raise ValueError(
                f"Parameter {p.name!r} is not frozen_before_test; it cannot "
                "enter a robustness sensitivity grid. Sensitivity testing an "
                "already-optimized parameter is parameter fishing by another name."
            )
        if not isinstance(p.value, (int, float)) or isinstance(p.value, bool):
            continue
        low = p.value * (1 - step_fraction)
        high = p.value * (1 + step_fraction)
        grid[p.name] = (
            [round(low), p.value, round(high)]
            if isinstance(p.value, int)
            else [round(low, 6), p.value, round(high, 6)]
        )
    return grid


@dataclass
class RobustnessReport:
    cost_sensitivity: list[PerturbationResult] = field(default_factory=list)
    slippage_sensitivity: list[PerturbationResult] = field(default_factory=list)
    timing_perturbation: list[PerturbationResult] = field(default_factory=list)
    universe_sensitivity: list[PerturbationResult] = field(default_factory=list)
    period_sensitivity: list[PerturbationResult] = field(default_factory=list)
    parameter_sensitivity: list[PerturbationResult] = field(default_factory=list)

    @property
    def all_results(self) -> list[PerturbationResult]:
        return [
            *self.cost_sensitivity, *self.slippage_sensitivity,
            *self.timing_perturbation, *self.universe_sensitivity,
            *self.period_sensitivity, *self.parameter_sensitivity,
        ]

    @property
    def survival_rate(self) -> float | None:
        results = self.all_results
        if not results:
            return None
        return round(sum(1 for r in results if r.survived) / len(results), 4)

    def to_dict(self) -> dict:
        return {
            "cost_sensitivity": [r.to_dict() for r in self.cost_sensitivity],
            "slippage_sensitivity": [r.to_dict() for r in self.slippage_sensitivity],
            "timing_perturbation": [r.to_dict() for r in self.timing_perturbation],
            "universe_sensitivity": [r.to_dict() for r in self.universe_sensitivity],
            "period_sensitivity": [r.to_dict() for r in self.period_sensitivity],
            "parameter_sensitivity": [r.to_dict() for r in self.parameter_sensitivity],
            "survival_rate": self.survival_rate,
        }
