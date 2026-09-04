"""V5 — the standardized research report.

One function, `render`, turns an `EvaluationResult` plus a `Decision` into
`docs/research/<hypothesis_id>/<run_id>.md` following the 24-section
structure the phase brief specifies.

**Three registers, kept visibly separate throughout**, per the brief's
instruction not to blur them:

- **OBSERVED** — a number the engine produced.
- **INTERPRETED** — what a section's author reads into that number.
- **NOT ESTABLISHED** — a claim this run's evidence does not support,
  stated as such rather than left unsaid.

The word "proves" does not appear anywhere in this module's templates.
"""

from __future__ import annotations

import pathlib

from experiments.alpha.decision import Decision
from experiments.alpha.evaluator import EvaluationResult
from experiments.alpha.hypothesis import AlphaHypothesis

REPORT_ROOT = pathlib.Path("docs/research")


def _fmt(value: float | None, *, pct: bool = False, digits: int = 4) -> str:
    if value is None:
        return "NOT ESTABLISHED (undefined)"
    return f"{value * 100:.2f}%" if pct else f"{value:.{digits}f}"


def render(
    hypothesis: AlphaHypothesis, result: EvaluationResult, decision: Decision
) -> str:
    meta = hypothesis.metadata
    lines: list[str] = []

    def h(level: int, title: str) -> None:
        lines.append(f"\n{'#' * level} {title}\n")

    def p(text: str) -> None:
        lines.append(text)

    # 1. Executive summary --------------------------------------------------------
    h(1, f"{meta.hypothesis_name} — Research Report")
    p(f"**Hypothesis id:** `{meta.hypothesis_id}`  ")
    p(f"**Run id:** `{result.run_id}`  ")
    p(f"**Decision:** **{decision.status}** ({decision.status.name})  ")
    p(f"**Thresholds version:** `{decision.thresholds_version}`")

    h(2, "1. Executive summary")
    primary = result.testing_ledger.primary_metric if result.testing_ledger else "sharpe"
    verdict_label = decision.status.name.replace("_", " ").title()
    p(
        f"OBSERVED: primary-metric ({primary}) control percentile and decision "
        f"reasons are listed in §22. "
        f"INTERPRETED verdict: **{decision.status} — {verdict_label}**."
    )
    if result.test_contaminated:
        p(
            "**TEST_CONTAMINATED.** This hypothesis's TEST period has been "
            "observed more than once. Any TEST-period figures below are "
            "reported for completeness but MUST NOT be read as clean "
            "out-of-sample evidence."
        )

    # 2-3. Hypothesis + mechanism --------------------------------------------------
    h(2, "2. Hypothesis")
    p(f"**Name:** {meta.hypothesis_name}")
    p(f"**Researcher:** {meta.researcher}")
    p(f"**Created:** {meta.creation_timestamp.isoformat()}")

    h(2, "3. Economic mechanism")
    p(meta.economic_mechanism)
    p(f"**Expected direction:** {meta.expected_direction}")
    p(f"**Expected holding period:** {meta.expected_holding_period}")
    p(f"**Expected market behavior:** {meta.expected_market_behavior}")

    # 4-6. Data ----------------------------------------------------------------------
    h(2, "4. Data")
    p(f"**Required features:** {', '.join(meta.required_features)}")
    p(f"**Data dependencies:** {', '.join(meta.data_dependencies)}")
    p(f"**Dataset snapshot:** `{result.manifest.dataset_snapshot}`")

    h(2, "5. Universe")
    p(f"OBSERVED universe ({len(result.manifest.universe)} names): "
      f"{', '.join(result.manifest.universe)}")

    h(2, "6. Dataset limitations")
    contract = result.dataset_contract
    p(f"**Universe type:** {contract.universe_type}  ")
    p(f"**Survivorship bias risk:** {contract.survivorship_bias_risk}  ")
    p(f"**Corporate-action quality:** {contract.corporate_action_quality}  ")
    p(f"**Delisted-security coverage:** {contract.delisted_security_coverage}")
    warnings = contract.warnings()
    if warnings:
        p("\n**Warnings (must accompany any use of this run's numbers):**")
        for w in warnings:
            p(f"- {w}")

    # 7-8. Parameters + provenance ----------------------------------------------------
    h(2, "7. Parameters")
    for param in hypothesis.parameters.parameters:
        p(f"- `{param.name}` = `{param.value}` ({param.source})")

    h(2, "8. Parameter provenance")
    if hypothesis.parameters.any_contaminated:
        p(
            f"**CONTAMINATED parameters present:** "
            f"{', '.join(hypothesis.parameters.contaminated_names)}. "
            "These values were selected after observing results and MUST "
            "NOT be presented as ex-ante."
        )
    else:
        p("All parameters are `frozen_before_test=True`, `selected_after_observation=False`.")
    for param in hypothesis.parameters.parameters:
        p(f"- `{param.name}`: {param.justification}")

    # 9. Protocol ----------------------------------------------------------------------
    h(2, "9. Experimental protocol")
    p(
        "Stages 1-9 of the V5 standardized protocol "
        "(`experiments.alpha.evaluator.AlphaEvaluator.evaluate`): data "
        "validation, deterministic baseline, benchmark, matched random "
        "control, concentration, walk-forward, regime conditioning, "
        "robustness, placebo."
    )

    # 10-11. Baseline + benchmark ---------------------------------------------------
    h(2, "10. Baseline results")
    for period_name, run in result.baseline.items():
        m = run.performance
        p(
            f"- **{period_name}**: OBSERVED CAGR {_fmt(m.cagr, pct=True)}, "
            f"Sharpe {_fmt(m.sharpe)}, trades {m.trade_count}, "
            f"certified={run.certified}"
        )

    h(2, "11. Benchmark results")
    for period_name, run in result.benchmark.items():
        m = run.performance
        p(f"- **{period_name}** (buy-and-hold): OBSERVED CAGR {_fmt(m.cagr, pct=True)}, "
          f"Sharpe {_fmt(m.sharpe)}")

    # 12. Random-control results ------------------------------------------------------
    h(2, "12. Random-control results")
    for period_name, rc in result.random_control.items():
        p(f"\n**{period_name}** ({rc.trials} trials):")
        for metric, comparison in rc.metrics.items():
            pct = comparison.get("percentile")
            pct_text = "NOT ESTABLISHED" if pct is None else f"{pct*100:.1f} pctile"
            p(f"  - {metric}: OBSERVED {comparison.get('observed')}, "
              f"null p50 {comparison.get('null_median')}, {pct_text}, "
              f"p={comparison.get('p_value')}")
        p(f"  - INTERPRETED: above-95th metrics = {rc.verdict.get('metrics_above_95th')}")

    # 13. Concentration -----------------------------------------------------------------
    h(2, "13. Concentration analysis")
    if result.concentration:
        c = result.concentration
        p(f"- OBSERVED top-1 share {_fmt(c.top_1_share, pct=True)}, "
          f"top-3 share {_fmt(c.top_3_share, pct=True)}, "
          f"top-5 share {_fmt(c.top_5_share, pct=True)}")
        p(f"- OBSERVED top contributor: {c.top_contributor} "
          f"({_fmt(c.top_contributor_share, pct=True)} of total P&L)")
        p(f"- OBSERVED Sharpe retention excluding top contributor: {_fmt(c.sharpe_retention)}")
        verdict_text = (
            "CONCENTRATION_DEPENDENT" if c.concentration_dependent
            else "not concentration-dependent"
        )
        p(f"- INTERPRETED: **{verdict_text}** — {c.reason}")

    # 14. Walk-forward --------------------------------------------------------------------
    h(2, "14. Walk-forward results")
    if result.walk_forward:
        wf = result.walk_forward
        p(f"OBSERVED fold win rate: {_fmt(wf.fold_win_rate, pct=True)} "
          f"({len(wf.folds)} folds, reported individually, not only pooled)")
        for fold in wf.folds:
            p(f"  - fold {fold['fold']['index']}: Sharpe {_fmt(fold.get('sharpe'))}, "
              f"CAGR {_fmt(fold.get('cagr'), pct=True)}, trades {fold.get('trade_count')}")
        if wf.dataset_audit is not None and not wf.dataset_audit.is_clean:
            p("- Dataset audit warnings: " + "; ".join(wf.dataset_audit.warnings()))

    # 15. Regime -----------------------------------------------------------------------------
    h(2, "15. Regime analysis")
    if result.regime and result.regime.selected_k:
        r = result.regime
        p(
            f"OBSERVED: K={r.selected_k} HMM states (V4.1's causal, "
            "walk-forward-fit model, reused unchanged)."
        )
        for state in r.states:
            p(f"  - state {state['state_id']} ({state['label']}): "
              f"occupancy {state['occupancy_share']*100:.1f}%")
        p(
            f"OBSERVED regime-conditioned control: beaten in "
            f"{r.regimes_beaten}/{r.regimes_total} regimes."
        )
        majority = r.regimes_total and r.regimes_beaten >= r.regimes_total // 2 + 1
        interp = "consistent across regimes" if majority else "NOT consistent across regimes"
        p(f"INTERPRETED: {interp}.")
    else:
        p("NOT ESTABLISHED — regime stage did not produce a stable K, or was not run.")

    # 16-17. Robustness + placebo ------------------------------------------------------------
    h(2, "16. Robustness")
    if result.robustness:
        rb = result.robustness
        p(f"OBSERVED survival rate across all perturbations: {_fmt(rb.survival_rate, pct=True)}")
        for group_name, group in (
            ("cost sensitivity", rb.cost_sensitivity),
            ("slippage sensitivity", rb.slippage_sensitivity),
            ("universe sensitivity", rb.universe_sensitivity),
            ("period sensitivity", rb.period_sensitivity),
        ):
            if group:
                survived = sum(1 for g in group if g.survived)
                p(f"  - {group_name}: {survived}/{len(group)} survived")

    h(2, "17. Placebo tests")
    p(f"Entry-timing placebo: {result.placebo.get('entry_timing_placebo', 'not run')}")
    fp = result.placebo.get("feature_permutation_placebo")
    if fp:
        p(f"Feature-permutation placebo: OBSERVED real Sharpe {_fmt(fp['real_sharpe'])} "
          f"vs placebo Sharpe {_fmt(fp['placebo_sharpe'])}")
    else:
        note = result.placebo.get("feature_permutation_placebo_note", "not applicable")
        p(f"Feature-permutation placebo: {note}")

    # 18. Multiple-testing context --------------------------------------------------------------
    h(2, "18. Multiple-testing context")
    if result.testing_ledger:
        tl = result.testing_ledger.to_dict()
        p(f"OBSERVED tests attempted: {tl['tests_attempted']}")
        p(f"Primary metric (fixed ex-ante): `{tl['primary_metric']}`")
        p(f"Secondary metrics inspected: {', '.join(tl['secondary_metrics'])}")
        p(f"Contamination status: **{tl['contamination_status']}**")

    # 19-20. Statistical + economic ------------------------------------------------------------
    h(2, "19. Statistical evidence")
    p("See §12 (random control) and §15 (regime-conditioned control) for the full "
      "percentile/p-value/effect-size tables. No single metric is treated as sufficient.")

    h(2, "20. Economic interpretation")
    p(
        "INTERPRETED: costs, turnover, and exposure are included in every "
        "figure above (§10-§16) — none of this report's numbers are gross-of-cost."
    )

    # 21. Failure modes ---------------------------------------------------------------------------
    h(2, "21. Failure modes")
    for mode in meta.known_failure_modes:
        p(f"- {mode}")
    p("\n**Falsification criteria stated ex-ante:**")
    for criterion in meta.falsification_criteria:
        p(f"- {criterion}")

    # 22. Final decision -------------------------------------------------------------------------
    h(2, "22. Final decision")
    p(f"**{decision.status} — {decision.status.name.replace('_', ' ').title()}**")
    p("Reasons:")
    for reason in decision.reasons:
        p(f"- `{reason}`")

    # 23. Reproducibility --------------------------------------------------------------------------
    h(2, "23. Reproducibility manifest")
    p(f"- git commit: `{result.manifest.git_commit}`")
    p(f"- working tree dirty at run time: {result.manifest.working_tree_dirty}")
    p(f"- dataset snapshot: `{result.manifest.dataset_snapshot}`")
    p(f"- random seed: `{result.manifest.random_seed}`")
    p(f"- hypothesis signature: `{result.manifest.hypothesis_signature}`")
    p(f"- manifest content hash: `{result.manifest.content_hash()}`")
    repro_text = (
        result.reproducible
        if result.reproducible is not None
        else "NOT ESTABLISHED (no rerun compared)"
    )
    p(f"- reproducible (verified rerun): {repro_text}")

    # 24. GO/NO-GO ------------------------------------------------------------------------------
    h(2, "24. GO / NO-GO")
    go = decision.status.value == "A"
    p(f"**{'GO' if go else 'NO-GO'}** for paper-trading candidacy.")
    if not go:
        p(
            "A human operator has not approved this hypothesis for paper "
            "trading. No automatic activation occurs from this report or "
            "from any part of this framework."
        )

    return "\n".join(lines) + "\n"


def write_report(
    hypothesis: AlphaHypothesis, result: EvaluationResult, decision: Decision
) -> pathlib.Path:
    directory = REPORT_ROOT / hypothesis.hypothesis_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.run_id}.md"
    path.write_text(render(hypothesis, result, decision), encoding="utf-8")
    return path
