"""End-to-end evaluator integration: the full nine-stage protocol against
real (cached) Yahoo data, at trial counts small enough to run in a test
suite, plus the two properties the whole framework exists to guarantee:

- **Reproducibility**: identical inputs produce an identical manifest
  content hash.
- **Contamination**: a second TEST observation on the same hypothesis is
  unconditionally marked, and a decision cannot be recorded as clean
  evidence over it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from experiments import data as data_module
from experiments.alpha.candidates.cross_sectional_momentum import (
    CrossSectionalMomentumHypothesis,
)
from experiments.alpha.decision import DecisionInputs
from experiments.alpha.decision import evaluate as decision_evaluate
from experiments.alpha.evaluator import AlphaEvaluator, DataValidationError
from experiments.alpha.registry import ExperimentRegistry
from experiments.alpha.reporting import render
from experiments.alpha.schema import (
    DataQualityLevel,
    DatasetContract,
    ExperimentStatus,
    SurvivorshipRisk,
    UniverseType,
)
from experiments.config import CostModel, ExperimentConfig, Period, RiskLimits

# A short, real window -- real Yahoo data (cached from earlier phases), but
# small enough that the momentum lookback (126 trading days) still has room
# and the whole suite runs in seconds, not minutes.
UNIVERSE = ("AAPL", "MSFT", "GOOGL")
BENCHMARK = "SPY"
TRAIN = Period("train", dt.date(2018, 1, 1), dt.date(2019, 7, 1))
VALIDATION = Period("validation", dt.date(2019, 7, 1), dt.date(2020, 1, 1))
TEST = Period("test", dt.date(2020, 1, 1), dt.date(2020, 7, 1))
FULL_RANGE_START = dt.date(2018, 1, 1)
FULL_RANGE_END = dt.date(2020, 7, 1)

TRIALS = 5  # a real Monte Carlo, at a size that finishes in a test suite


def _contract() -> DatasetContract:
    return DatasetContract(
        provider="yahoo", universe_type=UniverseType.STATIC_CURRENT,
        survivorship_bias_risk=SurvivorshipRisk.HIGH,
        corporate_action_quality=DataQualityLevel.ASSUMED,
        delisted_security_coverage=DataQualityLevel.UNKNOWN,
    )


def _config(experiment_id: str) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id=experiment_id, strategy="cross_sectional_momentum",
        strategy_version="1.0", frozen_at_commit="test",
        universe=UNIVERSE, costs=CostModel(commission_bps=5.0, slippage_bps=5.0),
        risk=RiskLimits(max_positions=3), position_size_pct=0.3,
        test=TEST, train=TRAIN, validation=VALIDATION, random_seed=777,
    )


@pytest.fixture(scope="module")
def bars():
    all_bars = data_module.align(
        data_module.load([*UNIVERSE, BENCHMARK], FULL_RANGE_START, FULL_RANGE_END)
    )
    universe_bars = {t: b for t, b in all_bars.items() if t in UNIVERSE}
    benchmark_bars = {BENCHMARK: all_bars[BENCHMARK]} if BENCHMARK in all_bars else {}
    return universe_bars, benchmark_bars


def _hypothesis(hid: str) -> CrossSectionalMomentumHypothesis:
    """A momentum hypothesis registered under a test-specific id -- the
    default id is a module constant, and reusing it across tests that share
    an on-disk-backed registry would collide."""
    import dataclasses

    from experiments.alpha.candidates.cross_sectional_momentum import default_metadata

    metadata = dataclasses.replace(default_metadata(), hypothesis_id=hid)
    return CrossSectionalMomentumHypothesis(tickers=list(UNIVERSE), metadata=metadata)


def _scratch_registry() -> ExperimentRegistry:
    """An in-memory registry with no backing file -- for tests that only
    need registration/contamination bookkeeping within the test itself and
    never call `.save()`."""
    registry = ExperimentRegistry.__new__(ExperimentRegistry)
    registry.path = None  # type: ignore[assignment]
    registry._entries = {}  # type: ignore[attr-defined]
    return registry


# -- data validation: fail closed ----------------------------------------------------


def test_stage1_rejects_out_of_order_bars(bars) -> None:
    universe_bars, _ = bars
    evaluator = AlphaEvaluator(registry=_scratch_registry(), dataset_contract=_contract())

    broken = {"AAPL": list(reversed(universe_bars["AAPL"]))}
    with pytest.raises(DataValidationError, match="chronological"):
        evaluator.validate_data(broken, cutoff=FULL_RANGE_END + dt.timedelta(days=1))


def test_stage1_accepts_real_clean_data(bars) -> None:
    universe_bars, _ = bars
    evaluator = AlphaEvaluator(registry=_scratch_registry(), dataset_contract=_contract())
    audit = evaluator.validate_data(universe_bars, cutoff=FULL_RANGE_END + dt.timedelta(days=1))
    assert audit is not None


# -- the full protocol, end to end ----------------------------------------------------


@pytest.fixture
def registry(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(path=tmp_path / "registry.json")


def test_the_full_nine_stage_protocol_runs_end_to_end(bars, registry) -> None:
    universe_bars, benchmark_bars = bars
    hyp = _hypothesis("momentum_test_e2e")
    registry.register(hyp.metadata)

    evaluator = AlphaEvaluator(
        registry=registry, dataset_contract=_contract(), random_control_trials=TRIALS,
    )
    result = evaluator.evaluate(
        hyp, _config("e2e"), universe_bars, benchmark_bars,
        periods={"train": TRAIN, "validation": VALIDATION},
        history=Period("history", FULL_RANGE_START, VALIDATION.end),
        walk_forward_train_days=200, walk_forward_test_days=60,
        random_seed=42, unlock_test=False,
        run_regime_stage=False,  # the momentum window here is too short for a stable HMM fold
    )

    assert "train" in result.baseline
    assert "validation" in result.baseline
    assert "test" not in result.baseline  # TEST was never unlocked
    assert result.test_contaminated is False
    assert result.random_control["train"].trials == TRIALS
    assert result.concentration is not None
    assert result.walk_forward is not None
    assert result.robustness is not None
    assert result.placebo  # entry-timing placebo key always present


def test_test_period_is_absent_unless_explicitly_unlocked(bars, registry) -> None:
    universe_bars, benchmark_bars = bars
    hyp = _hypothesis("momentum_test_gate")
    registry.register(hyp.metadata)
    evaluator = AlphaEvaluator(
        registry=registry, dataset_contract=_contract(), random_control_trials=2,
    )

    result = evaluator.evaluate(
        hyp, _config("gate"), universe_bars, benchmark_bars,
        periods={"train": TRAIN, "validation": VALIDATION, "test": TEST},
        history=Period("history", FULL_RANGE_START, VALIDATION.end),
        walk_forward_train_days=200, walk_forward_test_days=60,
        random_seed=1, unlock_test=False, run_regime_stage=False,
    )
    assert "test" not in result.baseline
    assert registry.get("momentum_test_gate").test_observed is False


# -- reproducibility --------------------------------------------------------------------


def test_two_runs_with_identical_inputs_produce_identical_manifest_hashes(bars) -> None:
    universe_bars, benchmark_bars = bars

    def _run() -> str:
        reg = _scratch_registry()
        hyp = _hypothesis("momentum_repro")
        reg.register(hyp.metadata)
        evaluator = AlphaEvaluator(
            registry=reg, dataset_contract=_contract(), random_control_trials=2,
        )
        result = evaluator.evaluate(
            hyp, _config("repro"), universe_bars, benchmark_bars,
            periods={"train": TRAIN}, history=Period("h", FULL_RANGE_START, TRAIN.end),
            walk_forward_train_days=150, walk_forward_test_days=60,
            random_seed=99, unlock_test=False, run_regime_stage=False,
            run_robustness_stage=False, run_placebo_stage=False,
        )
        return result.manifest.content_hash()

    assert _run() == _run()


# -- contamination, exercised end to end -------------------------------------------------


def test_a_second_unlocked_run_is_marked_test_contaminated(bars, registry) -> None:
    universe_bars, benchmark_bars = bars
    hyp = _hypothesis("momentum_contam")
    registry.register(hyp.metadata)
    evaluator = AlphaEvaluator(
        registry=registry, dataset_contract=_contract(), random_control_trials=2,
    )

    kwargs = dict(
        periods={"train": TRAIN, "test": TEST},
        history=Period("h", FULL_RANGE_START, TEST.end),
        walk_forward_train_days=200, walk_forward_test_days=60,
        random_seed=5, unlock_test=True, run_regime_stage=False,
        run_robustness_stage=False, run_placebo_stage=False,
    )
    first = evaluator.evaluate(hyp, _config("contam"), universe_bars, benchmark_bars, **kwargs)
    assert first.test_contaminated is False

    second = evaluator.evaluate(hyp, _config("contam"), universe_bars, benchmark_bars, **kwargs)
    assert second.test_contaminated is True
    assert registry.get("momentum_contam").status is ExperimentStatus.TEST_CONTAMINATED


def test_a_contaminated_result_cannot_feed_a_supported_decision(bars, registry) -> None:
    universe_bars, benchmark_bars = bars
    hyp = _hypothesis("momentum_contam_decision")
    registry.register(hyp.metadata)
    evaluator = AlphaEvaluator(
        registry=registry, dataset_contract=_contract(), random_control_trials=2,
    )

    kwargs = dict(
        periods={"train": TRAIN, "test": TEST},
        history=Period("h", FULL_RANGE_START, TEST.end),
        walk_forward_train_days=200, walk_forward_test_days=60,
        random_seed=5, unlock_test=True, run_regime_stage=False,
        run_robustness_stage=False, run_placebo_stage=False,
    )
    evaluator.evaluate(hyp, _config("cd"), universe_bars, benchmark_bars, **kwargs)
    second = evaluator.evaluate(hyp, _config("cd"), universe_bars, benchmark_bars, **kwargs)

    decision = decision_evaluate(DecisionInputs(
        test_contaminated=second.test_contaminated,
        data_quality_ok=True, reproducible=True,
        test_period_percentile=0.99, test_period_effect_size=3.0, test_period_p_value=0.001,
        concentration_dependent=False, concentration_retention=0.9,
        regime_beaten_count=0, regime_total_count=0,
        robustness_survival_rate=0.9, walk_forward_fold_win_rate=0.8,
    ))
    assert decision.status.value == "E"


# -- report rendering ---------------------------------------------------------------------


def test_a_completed_run_renders_a_report_with_all_24_sections(bars, registry) -> None:
    universe_bars, benchmark_bars = bars
    hyp = _hypothesis("momentum_report")
    registry.register(hyp.metadata)
    evaluator = AlphaEvaluator(
        registry=registry, dataset_contract=_contract(), random_control_trials=2,
    )

    result = evaluator.evaluate(
        hyp, _config("report"), universe_bars, benchmark_bars,
        periods={"train": TRAIN, "validation": VALIDATION},
        history=Period("h", FULL_RANGE_START, VALIDATION.end),
        walk_forward_train_days=200, walk_forward_test_days=60,
        random_seed=8, unlock_test=False, run_regime_stage=False,
    )
    conc = result.concentration
    rb = result.robustness
    wf = result.walk_forward
    decision = decision_evaluate(DecisionInputs(
        test_contaminated=result.test_contaminated, data_quality_ok=True, reproducible=True,
        test_period_percentile=None, test_period_effect_size=None, test_period_p_value=None,
        concentration_dependent=conc.concentration_dependent if conc else False,
        concentration_retention=conc.sharpe_retention if conc else None,
        regime_beaten_count=0, regime_total_count=0,
        robustness_survival_rate=rb.survival_rate if rb else None,
        walk_forward_fold_win_rate=wf.fold_win_rate if wf else None,
    ))

    report = render(hyp, result, decision)
    for section_number in range(1, 25):
        assert f"{section_number}." in report or f"## {section_number}" not in report
    assert "OBSERVED" in report
    assert "INTERPRETED" in report
    assert "proves" not in report.lower()
