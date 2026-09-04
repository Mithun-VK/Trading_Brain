"""Experiment 3 — causal walk-forward HMM regime detection.

The one property every function in this module exists to preserve:

    inference at time t uses only X_1 ... X_t (and a model fit on data
    strictly before t) -- never P(S_t | X_1 ... X_T) with T > t.

**Why hmmlearn's own `predict`/`predict_proba` are not used for inference.**
Both run the forward-*backward* algorithm over the entire array passed to
them -- that is smoothing, `P(S_t | X_1...X_T)`, and it uses every future
observation in the array to inform every past state. Fitting the model on
2016-2018 and then calling `.predict()` on 2016-2019 would let 2019's
volatility spike quietly re-label 2017 as a different state than a
contemporaneous 2017 observer would have seen. So this module implements
its own forward-only filter (`causal_filter`) using the fitted model's own
parameters, and never calls `.predict()` or `.predict_proba()`.

**Why the walk-forward scaler is fit once per fold, on the training prefix
only.** Standardising with the full series' mean and stdev bakes 2020's
crash and 2023's rally into every year's z-score, including years before
either happened. Each fold's scaler sees only what a contemporaneous
observer would have seen.

**Label switching.** A GaussianHMM's component ordering is arbitrary and
can permute between independent fits. States are re-identified across folds
by Hungarian-matching each fold's raw (un-standardised) state means against
the previous fold's -- a deterministic, documented method, never a numeric
ID treated as a persistent identity.

This module is diagnostic. It does not import anything from `ai/`,
`backtesting/`, or the MA strategy, and nothing here is optimised against
trading P&L -- model selection uses BIC/AIC/held-out likelihood/stability,
computed in `hmm_selection.py`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
from hmmlearn.hmm import GaussianHMM
from scipy.optimize import linear_sum_assignment
from scipy.special import logsumexp

from experiments.hmm_features import FeatureRow, usable_prefix

MIN_TRAIN_ROWS = 250  # roughly one trading year -- too little history is not a fold


@dataclass(frozen=True)
class Scaler:
    """Fit once, on a training prefix only. Never refit on inference data."""

    mean: np.ndarray
    std: np.ndarray

    def transform(self, x: np.ndarray) -> np.ndarray:
        safe_std = np.where(self.std > 1e-12, self.std, 1.0)
        return (x - self.mean) / safe_std

    def inverse(self, x: np.ndarray) -> np.ndarray:
        return x * self.std + self.mean


def fit_scaler(x: np.ndarray) -> Scaler:
    return Scaler(mean=x.mean(axis=0), std=x.std(axis=0))


def _log_gaussian_diag(x: np.ndarray, mean: np.ndarray, var: np.ndarray) -> np.ndarray:
    """log N(x; mean, diag(var)) for every row of x against one component."""
    var = np.maximum(var, 1e-9)
    return -0.5 * (
        np.sum(np.log(2 * np.pi * var))
        + np.sum(((x - mean) ** 2) / var, axis=1)
    )


def log_emissions(model: GaussianHMM, x: np.ndarray) -> np.ndarray:
    """(T, K) log-likelihood of each row under each state's diagonal Gaussian."""
    k = model.n_components
    out = np.zeros((x.shape[0], k))
    for state in range(k):
        var = np.diag(model.covars_[state])
        out[:, state] = _log_gaussian_diag(x, model.means_[state], var)
    return out


@dataclass
class FilterResult:
    """The causal filtering output: P(S_t | X_1..X_t) for every t, and the
    per-step log-likelihood the scaling constants give for free."""

    filtered: np.ndarray  # (T, K), rows sum to 1
    step_log_likelihood: np.ndarray  # (T,), log P(x_t | x_1..x_{t-1})

    @property
    def total_log_likelihood(self) -> float:
        return float(np.sum(self.step_log_likelihood))

    @property
    def states(self) -> np.ndarray:
        return np.argmax(self.filtered, axis=1)


def causal_filter(model: GaussianHMM, x: np.ndarray) -> FilterResult:
    """The forward algorithm, in log space, with per-step normalisation.

    The normalised forward variable at t IS the filtering posterior
    `P(S_t | X_1..X_t)` -- this is standard HMM theory, not an
    approximation. Forward-backward (smoothing) is a different, separate
    algorithm that this function does not run.
    """
    t_count = x.shape[0]
    k = model.n_components
    log_b = log_emissions(model, x)
    log_a = np.log(np.clip(model.transmat_, 1e-300, 1.0))
    log_pi = np.log(np.clip(model.startprob_, 1e-300, 1.0))

    log_alpha = np.zeros((t_count, k))
    step_ll = np.zeros(t_count)

    log_alpha[0] = log_pi + log_b[0]
    step_ll[0] = logsumexp(log_alpha[0])
    log_alpha[0] -= step_ll[0]

    for t in range(1, t_count):
        # log sum_j alpha[t-1,j] * A[j,k]  ==  logsumexp over j of
        # (log_alpha[t-1,j] + log_a[j,k]), for each k.
        prior = logsumexp(log_alpha[t - 1][:, None] + log_a, axis=0)
        log_alpha[t] = prior + log_b[t]
        step_ll[t] = logsumexp(log_alpha[t])
        log_alpha[t] -= step_ll[t]

    return FilterResult(filtered=np.exp(log_alpha), step_log_likelihood=step_ll)


_SEED_CEILING = 2**32 - 1  # numpy's RandomState accepts only this range


def fit_hmm(x: np.ndarray, k: int, seed: int, n_restarts: int = 5) -> GaussianHMM:
    """Fit with several random restarts, keep the highest-likelihood one.

    EM only finds a local optimum, and a single restart can land somewhere
    bad. Restarts are seeded deterministically from `seed` so the whole
    walk-forward is reproducible end to end.

    The derived per-restart seed is reduced modulo numpy's uint32 ceiling --
    without it, a base seed as ordinary as a date-shaped `20260904` combined
    with `walk_forward`'s per-fold offset overflows the accepted range and
    numpy raises before a single bar is fit.
    """
    best: GaussianHMM | None = None
    best_score = float("-inf")
    for i in range(n_restarts):
        model = GaussianHMM(
            n_components=k, covariance_type="diag", n_iter=200,
            random_state=(seed * 1000 + i) % _SEED_CEILING, tol=1e-4,
        )
        model.fit(x)
        score = model.score(x)
        if score > best_score:
            best_score, best = score, model
    assert best is not None
    return best


def align_states(
    previous_raw_means: np.ndarray | None, current_raw_means: np.ndarray
) -> np.ndarray:
    """A permutation mapping this fold's component indices onto persistent
    state identities, in **raw** feature units so folds with different
    scalers are still comparable.

    Deterministic Hungarian assignment minimising total squared distance
    between matched state centroids. With no previous fold, states are
    ordered by mean return ascending -- an arbitrary but fixed and
    documented starting convention.
    """
    if previous_raw_means is None:
        order = np.argsort(current_raw_means[:, 0])  # feature 0 = daily_return
        return np.argsort(order)  # permutation: old index -> new identity

    cost = np.zeros((len(current_raw_means), len(previous_raw_means)))
    for i, cur in enumerate(current_raw_means):
        for j, prev in enumerate(previous_raw_means):
            cost[i, j] = float(np.sum((cur - prev) ** 2))
    row_ind, col_ind = linear_sum_assignment(cost)
    mapping = np.zeros(len(current_raw_means), dtype=int)
    mapping[row_ind] = col_ind
    return mapping


@dataclass
class Fold:
    """One expanding-window step: fit on history before `infer_start`,
    filter causally through `infer_end`, keep only the inferred block."""

    infer_start: dt.date
    infer_end: dt.date
    train_rows: int
    model: GaussianHMM
    scaler: Scaler
    raw_means: np.ndarray  # (K, F), this fold's state means in raw units
    state_mapping: np.ndarray  # old component idx -> persistent state id
    bic: float
    aic: float
    train_log_likelihood: float
    held_out_log_likelihood: float
    dates: list[dt.date] = field(default_factory=list)
    persistent_states: list[int] = field(default_factory=list)
    filtered_probs: list[list[float]] = field(default_factory=list)  # aligned to persistent_states


@dataclass
class WalkForwardResult:
    k: int
    folds: list[Fold]
    skipped_reason: str = ""

    @property
    def total_held_out_log_likelihood(self) -> float:
        return sum(f.held_out_log_likelihood for f in self.folds)

    def labels_by_date(self) -> dict[dt.date, int]:
        out: dict[dt.date, int] = {}
        for fold in self.folds:
            out.update(dict(zip(fold.dates, fold.persistent_states, strict=True)))
        return out


def walk_forward(
    rows: list[FeatureRow],
    k: int,
    *,
    seed: int = 20260904,
    fold_years: int = 1,
) -> WalkForwardResult:
    """Expanding-window causal fit-then-infer, one fold per `fold_years`.

    Fold i fits on every usable row before the fold's start date, then
    filters causally through the fold's end date and keeps only the newly
    inferred rows -- exactly the brief's example:

        2016-2018 -> infer 2019
        2016-2019 -> infer 2020
        ...
    """
    usable = usable_prefix(rows)
    if len(usable) < MIN_TRAIN_ROWS * 2:
        return WalkForwardResult(k=k, folds=[], skipped_reason=(
            f"Only {len(usable)} usable rows; need at least "
            f"{MIN_TRAIN_ROWS * 2} for one training fold plus one inference fold."
        ))

    first_year = usable[0].date.year
    last_year = usable[-1].date.year

    folds: list[Fold] = []
    previous_raw_means: np.ndarray | None = None
    fold_index = 0

    for year in range(first_year + 2, last_year + 1, fold_years):
        infer_start = dt.date(year, 1, 1)
        infer_end = dt.date(year + fold_years, 1, 1)

        train_rows = [r for r in usable if r.date < infer_start]
        infer_rows = [r for r in usable if infer_start <= r.date < infer_end]
        if len(train_rows) < MIN_TRAIN_ROWS or not infer_rows:
            continue

        x_train_raw = np.array([r.values for r in train_rows])
        scaler = fit_scaler(x_train_raw)
        x_train = scaler.transform(x_train_raw)

        model = fit_hmm(x_train, k, seed=seed + fold_index)
        fold_index += 1

        raw_means = np.array([scaler.inverse(m) for m in model.means_])
        mapping = align_states(previous_raw_means, raw_means)
        previous_raw_means = raw_means[np.argsort(mapping)]  # keep in persistent order

        # Filter causally over the WHOLE history through this fold's end --
        # the recursion is sequential and only ever looks backward, so
        # extending it further back costs nothing in causality, only in
        # (here, negligible) compute. Only the newly inferred tail is kept.
        all_through_fold = [r for r in usable if r.date < infer_end]
        x_all = scaler.transform(np.array([r.values for r in all_through_fold]))
        result = causal_filter(model, x_all)

        n_infer = len(infer_rows)
        infer_filtered = result.filtered[-n_infer:]
        infer_ll = result.step_log_likelihood[-n_infer:]
        persistent = [int(mapping[s]) for s in np.argmax(infer_filtered, axis=1)]
        reordered_probs = infer_filtered[:, np.argsort(mapping)]

        folds.append(
            Fold(
                infer_start=infer_start,
                infer_end=infer_end,
                train_rows=len(train_rows),
                model=model,
                scaler=scaler,
                raw_means=raw_means[np.argsort(mapping)],
                state_mapping=mapping,
                bic=float(model.bic(x_train)),
                aic=float(model.aic(x_train)),
                train_log_likelihood=float(model.score(x_train)),
                held_out_log_likelihood=float(np.sum(infer_ll)),
                dates=[r.date for r in infer_rows],
                persistent_states=persistent,
                filtered_probs=reordered_probs.tolist(),
            )
        )

    return WalkForwardResult(k=k, folds=folds)
