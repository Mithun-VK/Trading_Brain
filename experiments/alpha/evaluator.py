"""V5 — the standardized evaluation protocol.

One evaluator, run against any registered `AlphaHypothesis`, executing the
nine stages from the phase brief in order. Every stage reuses existing
infrastructure rather than reimplementing it:

    Stage 1  data validation        -> experiments.walkforward.audit_dataset,
                                        assert_no_future_bars
    Stage 2  deterministic baseline -> experiments.runner.run (V2's engine)
    Stage 3  benchmark               -> runner.run with BuyAndHoldStrategy
    Stage 4  matched random control -> experiments.random_control + montecarlo
    Stage 5  concentration           -> experiments.alpha.controls
    Stage 6  walk-forward            -> experiments.walkforward.rolling_folds
    Stage 7  regime conditioning     -> experiments.hmm_regime/hmm_selection/
                                        hmm_trade_analysis (V4's causal HMM)
    Stage 8  robustness               -> experiments.alpha.robustness
    Stage 9  placebo                 -> Stage 4's random control (always) +
                                        an optional feature-permutation
                                        placebo (`AlphaHypothesis.build_placebo_strategy`)

**The TEST gate is enforced here, not by convention.** `evaluate()` only
touches the TEST period when `unlock_test=True` is passed explicitly, and
the first time it is, `registry.mark_test_observed` is called -- which
means every subsequent call against the same hypothesis, with or without
`unlock_test`, permanently reports `test_contaminated=True` on the result.
There is no way to "peek" at TEST and later present a rerun as clean.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import random
from dataclasses import dataclass, field

from backtesting.strategy import BuyAndHoldStrategy
from data.ingestion.schemas import PriceBar
from experiments import (
    hmm_selection,
    hmm_trade_analysis,
    montecarlo,
    random_control,
    trade_analysis,
    walkforward,
)
from experiments.alpha import controls, robustness
from experiments.alpha import statistics as alpha_statistics
from experiments.alpha.hypothesis import AlphaHypothesis
from experiments.alpha.provenance import (
    RunManifest,
    current_git_commit,
    dataset_snapshot_for,
    is_working_tree_dirty,
    make_run_id,
)
from experiments.alpha.registry import ExperimentRegistry, RunRecord
from experiments.alpha.schema import DatasetContract
from experiments.config import ExperimentConfig, Period
from experiments.hmm_features import causal_features, usable_prefix
from experiments.hmm_regime import WalkForwardResult
from experiments.hmm_regime import walk_forward as hmm_walk_forward
from experiments.metrics import PerformanceRecord
from experiments.runner import ExperimentRun, describe_data
from experiments.runner import run as run_backtest
from experiments.walkforward import DatasetAudit

DEFAULT_RANDOM_CONTROL_TRIALS = 5000
PRIMARY_METRIC = "sharpe"
SECONDARY_METRICS = (
    "cagr", "sortino", "calmar", "total_return", "max_drawdown", "win_rate",
    "profit_factor", "expectancy",
)
HMM_K = 3  # the K selected and justified for this universe in V4.1; not re-selected here
HMM_SEED = 20260904  # V4.1's seed, reused so the regime labels are identical, not re-derived


class DataValidationError(Exception):
    """Stage 1 failed. The evaluator fails closed -- no later stage runs."""


class TestGateError(Exception):
    """An attempt to read TEST results without explicitly unlocking them."""


def _window(bars: dict[str, list[PriceBar]], period: Period) -> dict[str, list[PriceBar]]:
    return {
        ticker: [b for b in series if period.contains(b.ts.date())]
        for ticker, series in bars.items()
    }


@dataclass
class RandomControlResult:
    trials: int
    metrics: dict[str, dict] = field(default_factory=dict)  # metric -> NullComparison.to_dict()
    verdict: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"trials": self.trials, "metrics": self.metrics, "verdict": self.verdict}


@dataclass
class WalkForwardStageResult:
    folds: list[dict] = field(default_factory=list)
    fold_win_rate: float | None = None  # share of folds where OOS Sharpe > 0
    dataset_audit: DatasetAudit | None = None

    def to_dict(self) -> dict:
        return {
            "folds": self.folds,
            "fold_win_rate": self.fold_win_rate,
            "dataset_audit_clean": self.dataset_audit.is_clean if self.dataset_audit else None,
            "dataset_audit_warnings": self.dataset_audit.warnings() if self.dataset_audit else [],
        }


@dataclass
class RegimeStageResult:
    selected_k: int | None
    states: list[dict] = field(default_factory=list)
    by_state: list[dict] = field(default_factory=list)
    conditioned_control: dict = field(default_factory=dict)  # state -> comparison
    regimes_beaten: int = 0
    regimes_total: int = 0

    def to_dict(self) -> dict:
        return {
            "selected_k": self.selected_k,
            "states": self.states,
            "by_state": self.by_state,
            "conditioned_control": self.conditioned_control,
            "regimes_beaten": self.regimes_beaten,
            "regimes_total": self.regimes_total,
        }


@dataclass
class EvaluationResult:
    run_id: str
    hypothesis_id: str
    manifest: RunManifest
    test_contaminated: bool
    data_quality_ok: bool
    reproducible: bool | None  # None until a rerun has actually been compared
    dataset_contract: DatasetContract

    baseline: dict[str, ExperimentRun] = field(default_factory=dict)  # period -> run
    benchmark: dict[str, ExperimentRun] = field(default_factory=dict)
    random_control: dict[str, RandomControlResult] = field(default_factory=dict)
    concentration: controls.ConcentrationVerdict | None = None
    walk_forward: WalkForwardStageResult | None = None
    regime: RegimeStageResult | None = None
    robustness: robustness.RobustnessReport | None = None
    placebo: dict = field(default_factory=dict)
    testing_ledger: alpha_statistics.TestingLedger | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "hypothesis_id": self.hypothesis_id,
            "manifest": self.manifest.to_dict(),
            "test_contaminated": self.test_contaminated,
            "data_quality_ok": self.data_quality_ok,
            "reproducible": self.reproducible,
            "baseline": {p: r.headline() for p, r in self.baseline.items()},
            "benchmark": {p: r.headline() for p, r in self.benchmark.items()},
            "random_control": {p: r.to_dict() for p, r in self.random_control.items()},
            "concentration": self.concentration.to_dict() if self.concentration else None,
            "walk_forward": self.walk_forward.to_dict() if self.walk_forward else None,
            "regime": self.regime.to_dict() if self.regime else None,
            "robustness": self.robustness.to_dict() if self.robustness else None,
            "placebo": self.placebo,
            "testing_ledger": self.testing_ledger.to_dict() if self.testing_ledger else None,
        }


class AlphaEvaluator:
    """Runs the nine-stage protocol against one hypothesis's data window."""

    def __init__(
        self,
        registry: ExperimentRegistry,
        *,
        dataset_contract: DatasetContract,
        random_control_trials: int = DEFAULT_RANDOM_CONTROL_TRIALS,
    ) -> None:
        self.registry = registry
        self.dataset_contract = dataset_contract
        self.random_control_trials = random_control_trials

    # -- Stage 1 -----------------------------------------------------------------

    def validate_data(
        self, bars_by_ticker: dict[str, list[PriceBar]], *, cutoff: dt.date
    ) -> DatasetAudit:
        """Fail closed. No stage after this one runs on data that failed
        the check."""
        if not bars_by_ticker or not any(bars_by_ticker.values()):
            raise DataValidationError("No bars supplied. There is nothing to evaluate.")
        for ticker, bars in bars_by_ticker.items():
            stamps = [b.ts for b in bars]
            if stamps != sorted(stamps):
                raise DataValidationError(f"{ticker}: bars are not in chronological order.")
            if len(stamps) != len(set(stamps)):
                raise DataValidationError(f"{ticker}: duplicate timestamps present.")
        try:
            walkforward.assert_no_future_bars(bars_by_ticker, cutoff=cutoff)
        except walkforward.LeakageError as exc:
            raise DataValidationError(str(exc)) from exc
        return walkforward.audit_dataset(bars_by_ticker)

    # -- Stages 2-3: baseline + benchmark -----------------------------------------

    def run_baseline(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        bars_by_ticker: dict[str, list[PriceBar]],
        benchmark_bars: dict[str, list[PriceBar]],
        *,
        periods: dict[str, Period],
        unlock_test: bool,
    ) -> tuple[dict[str, ExperimentRun], dict[str, ExperimentRun]]:
        baseline: dict[str, ExperimentRun] = {}
        benchmark: dict[str, ExperimentRun] = {}

        for name, period in periods.items():
            if name == "test" and not unlock_test:
                continue
            window = _window(bars_by_ticker, period)
            provenance = describe_data(window, provider=config.experiment_id)
            baseline[name] = run_backtest(
                config, hypothesis.build_strategy(), window,
                provider=provenance.provider, period=name, provenance=provenance,
            )

            bench_window = _window(benchmark_bars, period)
            bench_provenance = describe_data(bench_window, provider=config.experiment_id)
            bench_config = dataclasses.replace(config, position_size_pct=1.0)
            benchmark[name] = run_backtest(
                bench_config, BuyAndHoldStrategy(tickers=list(benchmark_bars)),
                bench_window, provider=bench_provenance.provider, period=name,
                provenance=bench_provenance,
            )

        return baseline, benchmark

    # -- Stage 4: matched random control -------------------------------------------

    def run_random_control(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        window: dict[str, list[PriceBar]],
        *,
        period_name: str,
        seed: int,
        trials: int | None = None,
    ) -> tuple[RandomControlResult, ExperimentRun]:
        """Returns the control comparison, plus the hypothesis's own run
        over this window (the caller may already have it from Stage 2, but
        this is kept self-contained so Stage 4 can run in isolation, e.g.
        for a single regime-conditioned period in Stage 7)."""
        trials = trials if trials is not None else self.random_control_trials
        provenance = describe_data(window, provider=config.experiment_id)

        hyp_run = run_backtest(
            config, hypothesis.build_strategy(), window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        assert hyp_run.result is not None
        records = trade_analysis.enrich(hyp_run.result, window)
        target = random_control.target_from(records, window)

        metrics = list((PRIMARY_METRIC, *SECONDARY_METRICS))
        null: dict[str, list[float | None]] = {m: [] for m in metrics}

        for trial in range(trials):
            rng = random.Random(f"{seed}-{period_name}-{trial}")
            plan = random_control.build_plan(target, window, rng)
            control_run = run_backtest(
                config, random_control.RandomEntryStrategy(plan), window,
                provider=provenance.provider, period=period_name, provenance=provenance,
            )
            for m in metrics:
                null[m].append(getattr(control_run.performance, m, None))

        observed = {m: getattr(hyp_run.performance, m, None) for m in metrics}
        evaluations = alpha_statistics.evaluate_metrics(
            observed, null, primary_metric=PRIMARY_METRIC
        )
        verdict = alpha_statistics.summarize(evaluations, primary_metric=PRIMARY_METRIC)
        result = RandomControlResult(
            trials=trials,
            metrics={m: ev.to_dict() for m, ev in evaluations.items()},
            verdict=verdict,
        )
        return result, hyp_run

    # -- Stage 5: concentration ---------------------------------------------------

    def run_concentration(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        window: dict[str, list[PriceBar]],
        *,
        period_name: str,
        full_run: ExperimentRun,
    ) -> controls.ConcentrationVerdict:
        assert full_run.result is not None
        records = trade_analysis.enrich(full_run.result, window)
        by_ticker = trade_analysis.by_ticker(records)
        if not by_ticker:
            return controls.analyze(records, full_sharpe=None, sharpe_excluding_top=None)

        top = max(by_ticker, key=lambda t: by_ticker[t]["total_pnl"])
        reduced_window = {t: b for t, b in window.items() if t != top}
        provenance = describe_data(reduced_window, provider=config.experiment_id)
        reduced_run = run_backtest(
            config, hypothesis.build_strategy(), reduced_window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        return controls.analyze(
            records,
            full_sharpe=full_run.performance.sharpe,
            sharpe_excluding_top=reduced_run.performance.sharpe,
        )

    # -- Stage 6: walk-forward -----------------------------------------------------

    def run_walk_forward(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        bars_by_ticker: dict[str, list[PriceBar]],
        *,
        history: Period,
        train_days: int,
        test_days: int,
        validation_days: int = 0,
    ) -> WalkForwardStageResult:
        folds = walkforward.rolling_folds(
            history, train_days=train_days, validation_days=validation_days,
            test_days=test_days,
        )
        fold_reports = []
        wins = 0
        for fold in folds:
            test_window = _window(bars_by_ticker, fold.test)
            provenance = describe_data(test_window, provider=config.experiment_id)
            fold_run = run_backtest(
                config, hypothesis.build_strategy(), test_window,
                provider=provenance.provider, period=f"fold_{fold.index}", provenance=provenance,
            )
            sharpe = fold_run.performance.sharpe
            if sharpe is not None and sharpe > 0:
                wins += 1
            fold_reports.append({
                "fold": fold.to_dict(),
                "sharpe": sharpe,
                "cagr": fold_run.performance.cagr,
                "trade_count": fold_run.performance.trade_count,
            })

        return WalkForwardStageResult(
            folds=fold_reports,
            fold_win_rate=round(wins / len(folds), 4) if folds else None,
            dataset_audit=walkforward.audit_dataset(bars_by_ticker),
        )

    # -- Stage 7: regime conditioning -----------------------------------------------

    def run_regime_conditioning(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        window: dict[str, list[PriceBar]],
        benchmark_bars: list[PriceBar],
        *,
        period_name: str,
        trials: int,
        seed: int,
        k: int = HMM_K,
    ) -> RegimeStageResult:
        """Reuses V4's causal HMM exactly: `hmm_regime.walk_forward` for
        the state assignments, `hmm_selection.characterize` for their
        description. K is not re-selected here -- it is a property of the
        market (SPY), already justified in V4.1, not of this hypothesis.
        """
        feature_rows = causal_features(benchmark_bars)
        usable = usable_prefix(feature_rows)
        rows_by_date = {r.date: r.values for r in usable}
        wf: WalkForwardResult = hmm_walk_forward(feature_rows, k, seed=HMM_SEED)
        if not wf.folds:
            return RegimeStageResult(selected_k=None)

        labels_by_date = wf.labels_by_date()
        states = hmm_selection.characterize(wf, rows_by_date)

        provenance = describe_data(window, provider=config.experiment_id)
        hyp_run = run_backtest(
            config, hypothesis.build_strategy(), window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        assert hyp_run.result is not None
        records = trade_analysis.enrich(hyp_run.result, window)
        enriched = hmm_trade_analysis.attach(records, labels_by_date)
        by_state = hmm_trade_analysis.by_state(enriched)
        ma_by_state = {s.state: s for s in by_state}

        target = random_control.target_from(records, window)
        null_by_state: dict[int, list[float | None]] = {}
        for trial in range(trials):
            rng = random.Random(f"{seed}-regime-{trial}")
            plan = random_control.build_plan(target, window, rng)
            control_run = run_backtest(
                config, random_control.RandomEntryStrategy(plan), window,
                provider=provenance.provider, period=period_name, provenance=provenance,
            )
            assert control_run.result is not None
            control_records = trade_analysis.enrich(control_run.result, window)
            for stat in hmm_trade_analysis.by_state(
                hmm_trade_analysis.attach(control_records, labels_by_date)
            ):
                null_by_state.setdefault(stat.state, []).append(stat.expectancy)

        conditioned: dict[str, dict] = {}
        beaten = 0
        covered_states = [sid for sid in ma_by_state if sid != hmm_trade_analysis.NO_LABEL]
        for state_id in covered_states:
            ma_stat = ma_by_state[state_id]
            comparison = montecarlo.compare(
                f"state_{state_id}_expectancy", ma_stat.expectancy,
                null_by_state.get(state_id, []),
            )
            conditioned[str(state_id)] = comparison.to_dict()
            if comparison.percentile is not None and comparison.percentile >= 0.95:
                beaten += 1

        return RegimeStageResult(
            selected_k=k,
            states=[s.to_dict() for s in states],
            by_state=[s.to_dict() for s in by_state],
            conditioned_control=conditioned,
            regimes_beaten=beaten,
            regimes_total=len(covered_states),
        )

    # -- Stage 8: robustness --------------------------------------------------------

    def run_robustness(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        window: dict[str, list[PriceBar]],
        *,
        period_name: str,
        walk_forward_result: WalkForwardStageResult | None = None,
    ) -> robustness.RobustnessReport:
        provenance = describe_data(window, provider=config.experiment_id)
        baseline_run = run_backtest(
            config, hypothesis.build_strategy(), window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        baseline_sharpe = baseline_run.performance.sharpe

        report = robustness.RobustnessReport()

        for label, perturbed_config in robustness.cost_multiplier_configs(config):
            run = run_backtest(
                perturbed_config, hypothesis.build_strategy(), window,
                provider=provenance.provider, period=period_name, provenance=provenance,
            )
            report.cost_sensitivity.append(
                robustness.PerturbationResult(
                    label=label, metrics=run.performance,
                    survived=robustness.survives(baseline_sharpe, run.performance.sharpe),
                )
            )

        for label, perturbed_config in robustness.slippage_multiplier_configs(config):
            run = run_backtest(
                perturbed_config, hypothesis.build_strategy(), window,
                provider=provenance.provider, period=period_name, provenance=provenance,
            )
            report.slippage_sensitivity.append(
                robustness.PerturbationResult(
                    label=label, metrics=run.performance,
                    survived=robustness.survives(baseline_sharpe, run.performance.sharpe),
                )
            )

        # Universe sensitivity: full universe vs. dropping the largest
        # contributor (reuses the same reduced window Stage 5 already
        # computed the concept for, run fresh here to keep this stage
        # independently callable).
        assert baseline_run.result is not None
        records = trade_analysis.enrich(baseline_run.result, window)
        by_ticker = trade_analysis.by_ticker(records)
        if by_ticker:
            top = max(by_ticker, key=lambda t: by_ticker[t]["total_pnl"])
            reduced = {t: b for t, b in window.items() if t != top}
            if reduced:
                red_prov = describe_data(reduced, provider=config.experiment_id)
                red_run = run_backtest(
                    config, hypothesis.build_strategy(), reduced,
                    provider=red_prov.provider, period=period_name, provenance=red_prov,
                )
                report.universe_sensitivity.append(
                    robustness.PerturbationResult(
                        label=f"excluding_{top}", metrics=red_run.performance,
                        survived=robustness.survives(baseline_sharpe, red_run.performance.sharpe),
                        note=f"largest contributor {top} removed",
                    )
                )

        if walk_forward_result is not None:
            for fold_data in walk_forward_result.folds:
                sharpe = fold_data.get("sharpe")
                report.period_sensitivity.append(
                    robustness.PerturbationResult(
                        label=f"fold_{fold_data['fold']['index']}",
                        metrics=PerformanceRecord(sharpe=sharpe, cagr=fold_data.get("cagr")),
                        survived=robustness.survives(baseline_sharpe, sharpe),
                    )
                )

        try:
            grid = robustness.parameter_sensitivity_grid(hypothesis.parameters.parameters)
        except ValueError as exc:
            report.parameter_sensitivity.append(
                robustness.PerturbationResult(
                    label="skipped", metrics=PerformanceRecord(), survived=False, note=str(exc),
                )
            )
            grid = {}

        for name, values in grid.items():
            for value in values:
                if value == hypothesis.parameters.as_values().get(name):
                    continue  # the baseline value itself, already covered above
                report.parameter_sensitivity.append(
                    robustness.PerturbationResult(
                        label=f"{name}={value}",
                        metrics=PerformanceRecord(),
                        survived=False,
                        note=(
                            "Parameter sensitivity requires a hypothesis-specific "
                            "reconstruction with the perturbed value; the generic "
                            "evaluator records the grid point without re-running "
                            "it here. See the hypothesis's own sensitivity test."
                        ),
                    )
                )

        return report

    # -- Stage 9: placebo -----------------------------------------------------------

    def run_placebo(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        window: dict[str, list[PriceBar]],
        *,
        period_name: str,
        seed: int,
        trials: int,
    ) -> dict:
        """The entry-timing placebo (Stage 4's random control) always
        counts as a placebo result -- a random-entry schedule has no
        signal by construction. A feature-permutation placebo is added
        only if the hypothesis supports one; if not, that is stated
        explicitly rather than silently omitted.
        """
        placebo_strategy = hypothesis.build_placebo_strategy(random.Random(seed))
        result: dict = {
            "entry_timing_placebo": "see stage_4_random_control",
            "feature_permutation_placebo": None,
        }
        if placebo_strategy is None:
            result["feature_permutation_placebo_note"] = (
                "Hypothesis does not implement build_placebo_strategy(); no "
                "cross-sectional feature to permute (or the hypothesis is "
                "single-ticker). Entry-timing placebo is the valid control here."
            )
            return result

        provenance = describe_data(window, provider=config.experiment_id)
        placebo_run = run_backtest(
            config, placebo_strategy, window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        real_run = run_backtest(
            config, hypothesis.build_strategy(), window,
            provider=provenance.provider, period=period_name, provenance=provenance,
        )
        comparison = montecarlo.compare(
            "sharpe", real_run.performance.sharpe, [placebo_run.performance.sharpe]
        )
        result["feature_permutation_placebo"] = {
            "real_sharpe": real_run.performance.sharpe,
            "placebo_sharpe": placebo_run.performance.sharpe,
            "comparison": comparison.to_dict(),
        }
        return result

    # -- orchestration: the full nine-stage protocol -------------------------------

    def evaluate(
        self,
        hypothesis: AlphaHypothesis,
        config: ExperimentConfig,
        bars_by_ticker: dict[str, list[PriceBar]],
        benchmark_bars: dict[str, list[PriceBar]],
        *,
        periods: dict[str, Period],
        history: Period,
        walk_forward_train_days: int,
        walk_forward_test_days: int,
        random_seed: int,
        unlock_test: bool = False,
        run_robustness_stage: bool = True,
        run_regime_stage: bool = True,
        run_placebo_stage: bool = True,
        regime_trials: int | None = None,
    ) -> EvaluationResult:
        """Stages 1-9, in order, against one hypothesis.

        `unlock_test=False` (the default) evaluates TRAIN and VALIDATION
        only -- exactly the phase brief's rule that TEST is consumed once,
        deliberately, not by default. Passing `unlock_test=True` runs TEST
        too and permanently marks the hypothesis `test_observed` in the
        registry; a later call with `unlock_test=True` against the same
        hypothesis id reports `test_contaminated=True` on the result,
        regardless of how good the numbers are.
        """
        cutoff = max(
            (b.ts.date() for bars in bars_by_ticker.values() for b in bars), default=dt.date.min
        )
        # Stage 1. Its return value is not stored here: it raises on any hard
        # failure (fail-closed), and Stage 6 computes its own dataset audit
        # for the walk-forward report -- storing a second copy here would be
        # redundant, not additional evidence.
        self.validate_data(bars_by_ticker, cutoff=cutoff + dt.timedelta(days=1))
        data_quality_ok = True

        snapshot = dataset_snapshot_for(bars_by_ticker)
        entry = self.registry.get(hypothesis.hypothesis_id)
        if entry.dataset_snapshot is None:
            entry.dataset_snapshot = snapshot

        already_contaminated = entry.test_observed and unlock_test
        if unlock_test:
            self.registry.mark_test_observed(hypothesis.hypothesis_id)
        test_contaminated = already_contaminated or (
            self.registry.get(hypothesis.hypothesis_id).status.value == "test_contaminated"
        )

        baseline, benchmark = self.run_baseline(
            hypothesis, config, bars_by_ticker, benchmark_bars,
            periods=periods, unlock_test=unlock_test,
        )

        random_control_results: dict[str, RandomControlResult] = {}
        stage4_runs: dict[str, ExperimentRun] = {}
        for name, period in periods.items():
            if name == "test" and not unlock_test:
                continue
            window = _window(bars_by_ticker, period)
            rc_result, rc_run = self.run_random_control(
                hypothesis, config, window, period_name=name, seed=random_seed,
            )
            random_control_results[name] = rc_result
            stage4_runs[name] = rc_run

        if unlock_test and "test" in stage4_runs:
            reference_period = "test"
        elif "validation" in stage4_runs:
            reference_period = "validation"
        elif "train" in stage4_runs:
            reference_period = "train"
        else:
            raise DataValidationError(
                "No period produced a run to serve as the reference for "
                "concentration/regime/robustness -- at least one of "
                "train/validation/test must be evaluated."
            )
        reference_run = stage4_runs[reference_period]
        reference_window = _window(bars_by_ticker, periods[reference_period])

        concentration = self.run_concentration(
            hypothesis, config, reference_window,
            period_name=reference_period, full_run=reference_run,
        )

        walk_forward_result = self.run_walk_forward(
            hypothesis, config, bars_by_ticker, history=history,
            train_days=walk_forward_train_days, test_days=walk_forward_test_days,
        )

        regime_result = None
        if run_regime_stage and benchmark_bars:
            benchmark_series = next(iter(benchmark_bars.values()))
            default_regime_trials = min(500, self.random_control_trials)
            regime_result = self.run_regime_conditioning(
                hypothesis, config, reference_window, benchmark_series,
                period_name=reference_period,
                trials=regime_trials if regime_trials is not None else default_regime_trials,
                seed=random_seed + 1,
            )

        robustness_result = None
        if run_robustness_stage:
            robustness_result = self.run_robustness(
                hypothesis, config, reference_window,
                period_name=reference_period, walk_forward_result=walk_forward_result,
            )

        placebo_result: dict = {}
        if run_placebo_stage:
            placebo_result = self.run_placebo(
                hypothesis, config, reference_window,
                period_name=reference_period, seed=random_seed + 2, trials=1,
            )

        run_id = make_run_id(hypothesis.hypothesis_id, hypothesis.signature(), random_seed)
        manifest = RunManifest(
            run_id=run_id,
            hypothesis_id=hypothesis.hypothesis_id,
            hypothesis_signature=hypothesis.signature(),
            git_commit=current_git_commit(),
            working_tree_dirty=is_working_tree_dirty(),
            dataset_snapshot=snapshot,
            dataset_contract=self.dataset_contract,
            universe=tuple(sorted(bars_by_ticker)),
            periods=periods,
            parameters=hypothesis.parameters,
            cost_model=config.costs,
            random_seed=random_seed,
            controls={
                "random_control_trials": self.random_control_trials,
                "regime_trials": regime_trials,
            },
            regime_model={"k": HMM_K, "seed": HMM_SEED} if regime_result else None,
            test_contaminated=test_contaminated,
        )
        manifest_path = manifest.save()
        self.registry.record_run(
            hypothesis.hypothesis_id,
            RunRecord(
                run_id=run_id, manifest_path=str(manifest_path),
                stage="full_protocol",
                result_summary={"test_contaminated": test_contaminated},
            ),
        )

        testing_ledger = alpha_statistics.TestingLedger(
            metrics_inspected=(PRIMARY_METRIC, *SECONDARY_METRICS),
            primary_metric=PRIMARY_METRIC,
            selection_metric=PRIMARY_METRIC,
            contamination_status="contaminated" if test_contaminated else "clean",
        )

        return EvaluationResult(
            run_id=run_id,
            hypothesis_id=hypothesis.hypothesis_id,
            manifest=manifest,
            test_contaminated=test_contaminated,
            data_quality_ok=data_quality_ok,
            reproducible=None,
            dataset_contract=self.dataset_contract,
            baseline=baseline,
            benchmark=benchmark,
            random_control=random_control_results,
            concentration=concentration,
            walk_forward=walk_forward_result,
            regime=regime_result,
            robustness=robustness_result,
            placebo=placebo_result,
            testing_ledger=testing_ledger,
        )
