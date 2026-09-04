"""Experiment 3 — model selection and state interpretation.

Selection criteria only, never trading P&L: BIC, AIC, held-out
log-likelihood, state persistence (average duration), state occupancy,
transition stability, and feature separation. `select_k` never sees a
Sharpe ratio or a dollar figure.

State interpretation is deliberately the last step, not the first: states
start as anonymous persistent integers, and only after their return,
volatility, and duration characteristics are computed does this module
attach a descriptive (not authoritative) label.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

import numpy as np

from experiments.hmm_features import FEATURE_NAMES
from experiments.hmm_regime import Fold, WalkForwardResult

MIN_OCCUPANCY_SHARE = 0.05  # a state seen less than 5% of the time is not a regime
MIN_AVERAGE_DURATION_DAYS = 5  # a state the filter exits daily is not a regime


@dataclass
class StateCharacteristics:
    """What a persistent state actually looked like. Computed, not
    assumed -- the label at the bottom is descriptive, never authoritative."""

    state_id: int
    occupancy: int
    occupancy_share: float
    mean_return: float
    volatility: float
    downside_volatility: float
    mean_drawdown: float
    mean_momentum: float
    average_duration_days: float
    runs: int
    label: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _runs(sequence: list[int], state: int) -> list[int]:
    """Consecutive-day run lengths for one state."""
    runs: list[int] = []
    current = 0
    for value in sequence:
        if value == state:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def characterize(
    result: WalkForwardResult, rows_by_date: dict[dt.date, tuple]
) -> list[StateCharacteristics]:
    """One entry per persistent state, from the assembled walk-forward
    label sequence -- not from any single fold's model, since folds are
    refit and the sequence is what a live system would actually have
    produced."""
    labels = result.labels_by_date()
    if not labels:
        return []

    ordered_dates = sorted(labels)
    sequence = [labels[d] for d in ordered_dates]
    total = len(sequence)
    states = sorted(set(sequence))

    out: list[StateCharacteristics] = []
    idx = {name: i for i, name in enumerate(FEATURE_NAMES)}

    for state in states:
        dates_in_state = [d for d in ordered_dates if labels[d] == state]
        values = [rows_by_date[d] for d in dates_in_state if d in rows_by_date]
        runs = _runs(sequence, state)

        def col(name: str, rows: list[tuple] = values) -> list[float]:
            return [v[idx[name]] for v in rows]

        out.append(
            StateCharacteristics(
                state_id=state,
                occupancy=len(dates_in_state),
                occupancy_share=round(len(dates_in_state) / total, 4),
                mean_return=round(statistics.mean(col("daily_return")), 6) if values else 0.0,
                volatility=round(statistics.mean(col("realised_vol_20d")), 6) if values else 0.0,
                downside_volatility=(
                    round(statistics.mean(col("downside_vol_20d")), 6) if values else 0.0
                ),
                mean_drawdown=round(statistics.mean(col("drawdown")), 6) if values else 0.0,
                mean_momentum=round(statistics.mean(col("return_60d")), 6) if values else 0.0,
                average_duration_days=round(statistics.mean(runs), 2) if runs else 0.0,
                runs=len(runs),
            )
        )

    _interpret(out)
    return sorted(out, key=lambda s: s.state_id)


def _interpret(states: list[StateCharacteristics]) -> None:
    """An empirical, descriptive tag -- computed from what was observed,
    never chosen to make the result read a particular way."""
    if not states:
        return
    vol_median = statistics.median(s.volatility for s in states)
    for s in states:
        vol_word = "high-volatility" if s.volatility >= vol_median else "low-volatility"
        if s.mean_return > 0.0003 and s.mean_drawdown > -0.05:
            direction = "positive-return"
        elif s.mean_return < -0.0003 or s.mean_drawdown < -0.15:
            direction = "negative-return"
        else:
            direction = "neutral"
        s.label = f"{vol_word} {direction} state"


def transition_matrix(result: WalkForwardResult) -> dict[str, dict[str, float]]:
    """Empirical transition frequencies from the assembled sequence.

    Not any single fold's `transmat_` -- those are fit-time parameters of
    models that no longer exist once the walk-forward moves on. This is
    what the persistent-state sequence the system actually produced looked
    like.
    """
    labels = result.labels_by_date()
    ordered_dates = sorted(labels)
    sequence = [labels[d] for d in ordered_dates]
    states = sorted(set(sequence))

    counts = {a: {b: 0 for b in states} for a in states}
    for a, b in zip(sequence, sequence[1:], strict=False):
        counts[a][b] += 1

    out: dict[str, dict[str, float]] = {}
    for a in states:
        total = sum(counts[a].values())
        out[str(a)] = {
            str(b): round(counts[a][b] / total, 4) if total else 0.0 for b in states
        }
    return out


@dataclass
class SelectionCandidate:
    k: int
    total_bic: float
    total_aic: float
    total_held_out_log_likelihood: float
    n_folds: int
    states: list[StateCharacteristics] = field(default_factory=list)
    min_occupancy_share: float = 0.0
    min_average_duration: float = 0.0
    min_feature_separation: float = 0.0
    passes_stability: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {**{k: v for k, v in self.__dict__.items() if k != "states"},
                "states": [s.to_dict() for s in self.states]}


def _feature_separation(folds: list[Fold]) -> float:
    """Smallest average pairwise distance between state centroids, in raw
    feature units, averaged across folds. A model whose states sit on top
    of each other is not describing anything the data actually supports."""
    if not folds:
        return 0.0
    per_fold = []
    for fold in folds:
        means = fold.raw_means
        if len(means) < 2:
            per_fold.append(0.0)
            continue
        dists = [
            float(np.linalg.norm(means[i] - means[j]))
            for i in range(len(means))
            for j in range(i + 1, len(means))
        ]
        per_fold.append(min(dists))
    return round(statistics.mean(per_fold), 6)


def select_k(
    results: dict[int, WalkForwardResult],
    rows_by_date: dict[dt.date, tuple],
) -> tuple[int | None, list[SelectionCandidate]]:
    """Rank K=2..5 on structure, never on trading P&L.

    Returns the selected K (or None, with candidates explaining why nothing
    qualified) and the full candidate table for the report.
    """
    candidates: list[SelectionCandidate] = []

    for k, result in sorted(results.items()):
        if not result.folds:
            candidates.append(SelectionCandidate(
                k=k, total_bic=0, total_aic=0, total_held_out_log_likelihood=0,
                n_folds=0, note=result.skipped_reason or "No folds were produced.",
            ))
            continue

        states = characterize(result, rows_by_date)
        min_occ = min((s.occupancy_share for s in states), default=0.0)
        min_dur = min((s.average_duration_days for s in states), default=0.0)
        min_sep = _feature_separation(result.folds)

        passes = (
            len(states) == k  # every state actually got used
            and min_occ >= MIN_OCCUPANCY_SHARE
            and min_dur >= MIN_AVERAGE_DURATION_DAYS
        )
        note = "" if passes else (
            f"Fails stability: min occupancy {min_occ:.1%} "
            f"(need >= {MIN_OCCUPANCY_SHARE:.0%}), "
            f"min average duration {min_dur:.1f}d "
            f"(need >= {MIN_AVERAGE_DURATION_DAYS}d)."
            if len(states) == k else
            f"Only {len(states)} of {k} states were ever the most likely "
            "state on any day -- the model collapsed."
        )

        candidates.append(
            SelectionCandidate(
                k=k,
                total_bic=round(sum(f.bic for f in result.folds), 2),
                total_aic=round(sum(f.aic for f in result.folds), 2),
                total_held_out_log_likelihood=round(result.total_held_out_log_likelihood, 2),
                n_folds=len(result.folds),
                states=states,
                min_occupancy_share=round(min_occ, 4),
                min_average_duration=round(min_dur, 2),
                min_feature_separation=min_sep,
                passes_stability=passes,
                note=note,
            )
        )

    stable = [c for c in candidates if c.passes_stability]
    if not stable:
        return None, candidates

    # Among stable candidates, prefer the one with the best (least negative)
    # causal held-out log-likelihood -- BIC/AIC are computed on training
    # data and reward complexity less reliably than genuine out-of-sample
    # performance does.
    best = max(stable, key=lambda c: c.total_held_out_log_likelihood)
    return best.k, candidates
