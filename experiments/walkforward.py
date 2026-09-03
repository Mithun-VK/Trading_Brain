"""V3 — chronological walk-forward validation.

One backtest over one period tells you what a strategy did once. It does
not tell you whether the strategy would have been chosen at the time, which
is the only question that matters.

Walk-forward answers that by rolling a train/validate/test window forward
through history and only ever measuring on data the strategy has not seen:

    TRAIN ─────► VALIDATE ──► TEST
                    │
                    ▼  roll
            TRAIN ─────► VALIDATE ──► TEST

The leakage controls are the substance of this module, not a footnote.
Every one of them describes a way results get better without the strategy
getting better:

**Look-ahead** — a fold's test window must begin at or after its train
window ends, and bars are filtered by timestamp, never by index.

**Timestamp alignment** — a bar stamped at a session close is knowable only
*after* that close. `available_at` makes the distinction explicit rather
than assuming the stamp is the availability time.

**Feature availability** — an indicator over N bars is unavailable until N
bars exist. Warm-up is deducted from the *train* window, never borrowed
from the test window.

**Survivorship** — a universe assembled today from names that still exist
today omits the ones that failed. This module cannot fix that, but it
records whether the universe was point-in-time, so a result computed over a
survivor-biased universe says so.

What this module does not do is more important than what it does: it never
selects a fold's parameters using that fold's test data. If it did, every
number it produced would be a training score wearing an out-of-sample
label.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from config.logging import get_logger
from data.ingestion.schemas import PriceBar
from experiments.config import ExperimentConfig, Period

logger = get_logger("experiments")


class LeakageError(ValueError):
    """A fold or dataset would have leaked future information."""


@dataclass(frozen=True)
class Fold:
    """One train/validate/test slice of history."""

    index: int
    train: Period
    validation: Period | None
    test: Period

    def __post_init__(self) -> None:
        if self.validation is not None:
            if self.validation.start < self.train.end:
                raise LeakageError(
                    f"Fold {self.index}: validation starts {self.validation.start} "
                    f"before train ends {self.train.end}."
                )
            if self.test.start < self.validation.end:
                raise LeakageError(
                    f"Fold {self.index}: test starts {self.test.start} before "
                    f"validation ends {self.validation.end}."
                )
        elif self.test.start < self.train.end:
            raise LeakageError(
                f"Fold {self.index}: test starts {self.test.start} before train "
                f"ends {self.train.end}."
            )

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict() if self.validation else None,
            "test": self.test.to_dict(),
        }


def rolling_folds(
    period: Period,
    *,
    train_days: int,
    validation_days: int,
    test_days: int,
    step_days: int | None = None,
    anchored: bool = False,
) -> list[Fold]:
    """Split a period into chronological folds.

    `anchored=True` grows the training window from a fixed origin rather
    than sliding it, which is the right choice when a strategy is meant to
    learn cumulatively. Sliding is the default because it also tests whether
    the strategy survives its own history going stale.
    """
    if train_days < 1 or test_days < 1:
        raise ValueError("train_days and test_days must both be at least 1")

    step = step_days or test_days
    folds: list[Fold] = []
    index = 0
    train_start = period.start

    while True:
        train_end = train_start + dt.timedelta(days=train_days)
        val_end = train_end + dt.timedelta(days=validation_days)
        test_end = val_end + dt.timedelta(days=test_days)
        if test_end > period.end:
            break

        folds.append(
            Fold(
                index=index,
                train=Period(
                    f"train_{index}",
                    period.start if anchored else train_start,
                    train_end,
                ),
                validation=(
                    Period(f"val_{index}", train_end, val_end) if validation_days > 0 else None
                ),
                test=Period(f"test_{index}", val_end, test_end),
            )
        )
        index += 1
        train_start = train_start + dt.timedelta(days=step)

    if not folds:
        raise ValueError(
            f"Period {period.name!r} spans {period.days} days, too short for "
            f"{train_days}+{validation_days}+{test_days}-day folds."
        )
    return folds


# -- leakage controls -----------------------------------------------------------


def available_at(bar: PriceBar, *, publication_lag: dt.timedelta | None = None) -> dt.datetime:
    """When a bar could actually have been acted on.

    A daily bar stamped at the session date is knowable only after that
    session closes. Treating the stamp as the availability time is the
    quietest form of look-ahead there is, because nothing about the data
    looks wrong -- the strategy simply performs better than it could have.
    """
    return bar.ts + (publication_lag or dt.timedelta(0))


def slice_bars(
    bars_by_ticker: dict[str, list[PriceBar]],
    period: Period,
    *,
    warmup_bars: int = 0,
    publication_lag: dt.timedelta | None = None,
) -> dict[str, list[PriceBar]]:
    """Bars a strategy may see for `period`.

    Warm-up bars are taken from *before* the period so an indicator is
    computable on the period's first day -- and they are only ever taken
    from the past. Borrowing them from the future is how a moving average
    ends up knowing where price is going.
    """
    out: dict[str, list[PriceBar]] = {}
    for ticker, bars in bars_by_ticker.items():
        ordered = sorted(bars, key=lambda b: b.ts)
        in_period = [
            b
            for b in ordered
            if period.contains(available_at(b, publication_lag=publication_lag).date())
        ]
        if warmup_bars > 0:
            before = [
                b
                for b in ordered
                if available_at(b, publication_lag=publication_lag).date() < period.start
            ]
            in_period = before[-warmup_bars:] + in_period
        if in_period:
            out[ticker] = in_period
    return out


def assert_no_future_bars(bars_by_ticker: dict[str, list[PriceBar]], cutoff: dt.date) -> None:
    """Fail loudly if any bar postdates the decision point."""
    offenders = [
        f"{ticker}@{bar.ts.date()}"
        for ticker, bars in bars_by_ticker.items()
        for bar in bars
        if bar.ts.date() >= cutoff
    ]
    if offenders:
        raise LeakageError(
            f"{len(offenders)} bar(s) at or after the {cutoff} cutoff would be "
            f"visible to a decision made then: {offenders[:5]}"
        )


@dataclass
class DatasetAudit:
    """What could not be ruled out about the data.

    Every field here is a bias this framework can *detect* but not fix.
    Recording them is the point: a walk-forward result over a
    survivor-biased universe is still survivor-biased, and saying so is the
    difference between a caveat and a lie.
    """

    point_in_time_universe: bool = False
    delisted_included: bool = False
    corporate_actions_applied: bool = False
    fundamentals_lagged: bool = False
    duplicate_timestamps: int = 0
    non_monotonic_series: list[str] = field(default_factory=list)
    gaps: dict[str, int] = field(default_factory=dict)

    def warnings(self) -> list[str]:
        out: list[str] = []
        if not self.point_in_time_universe:
            out.append(
                "Universe is not point-in-time: names that failed or were "
                "delisted before today are absent, so returns are biased "
                "upward by survivorship."
            )
        if not self.delisted_included:
            out.append("Delisted securities are excluded, compounding survivorship bias.")
        if not self.corporate_actions_applied:
            out.append(
                "Corporate actions are not confirmed applied: an unadjusted split "
                "reads as a catastrophic single-day return."
            )
        if not self.fundamentals_lagged:
            out.append(
                "Fundamentals are not confirmed lagged to their publication date; "
                "using a figure before it was reported is look-ahead."
            )
        if self.duplicate_timestamps:
            out.append(f"{self.duplicate_timestamps} duplicate timestamp(s) found.")
        if self.non_monotonic_series:
            out.append(f"Series not in time order: {self.non_monotonic_series}")
        return out

    @property
    def is_clean(self) -> bool:
        return not self.warnings()


def audit_dataset(
    bars_by_ticker: dict[str, list[PriceBar]],
    *,
    point_in_time_universe: bool = False,
    delisted_included: bool = False,
    corporate_actions_applied: bool = False,
    fundamentals_lagged: bool = False,
) -> DatasetAudit:
    """Inspect the data for the biases that can be detected mechanically,
    and record the operator's claims about the ones that cannot.

    The claims default to False. An unstated claim is treated as unmet,
    because "we did not check" and "it is fine" must not look the same.
    """
    audit = DatasetAudit(
        point_in_time_universe=point_in_time_universe,
        delisted_included=delisted_included,
        corporate_actions_applied=corporate_actions_applied,
        fundamentals_lagged=fundamentals_lagged,
    )

    for ticker, bars in bars_by_ticker.items():
        stamps = [b.ts for b in bars]
        if stamps != sorted(stamps):
            audit.non_monotonic_series.append(ticker)
        audit.duplicate_timestamps += len(stamps) - len(set(stamps))

        ordered = sorted(set(stamps))
        gaps = sum(
            1
            for a, b in zip(ordered, ordered[1:], strict=False)
            if (b - a).days > 4  # a long weekend plus a holiday
        )
        if gaps:
            audit.gaps[ticker] = gaps

    return audit


@dataclass
class WalkForwardPlan:
    """The folds plus what is known about the data they run over."""

    config: ExperimentConfig
    folds: list[Fold]
    audit: DatasetAudit
    warmup_bars: int = 0
    publication_lag: dt.timedelta = dt.timedelta(0)

    def summary(self) -> dict:
        return {
            "experiment": self.config.experiment_id,
            "config_fingerprint": self.config.fingerprint(),
            "folds": len(self.folds),
            "first_train_start": self.folds[0].train.start.isoformat() if self.folds else None,
            "last_test_end": self.folds[-1].test.end.isoformat() if self.folds else None,
            "warmup_bars": self.warmup_bars,
            "publication_lag_hours": self.publication_lag.total_seconds() / 3600,
            "dataset_clean": self.audit.is_clean,
            "dataset_warnings": self.audit.warnings(),
        }
