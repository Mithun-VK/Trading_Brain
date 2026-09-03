"""V3 — walk-forward and the leakage controls.

Every test here describes a way results get better without the strategy
getting better. That is the whole category of bug walk-forward exists to
catch, and none of them announce themselves — a leaking backtest looks
exactly like a good one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from data.ingestion.schemas import PriceBar
from experiments.config import Period
from experiments.walkforward import (
    DatasetAudit,
    Fold,
    LeakageError,
    assert_no_future_bars,
    audit_dataset,
    available_at,
    rolling_folds,
    slice_bars,
)

START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _bars(n: int, *, ticker_seed: float = 100.0, step_days: int = 1) -> list[PriceBar]:
    return [
        PriceBar(
            ts=START + dt.timedelta(days=i * step_days),
            open=ticker_seed + i, high=ticker_seed + i + 1, low=ticker_seed + i - 1,
            close=ticker_seed + i, volume=1_000, interval="1d", source="vendor",
        )
        for i in range(n)
    ]


# -- fold construction ----------------------------------------------------------


def test_folds_roll_forward_and_never_overlap_their_own_test() -> None:
    folds = rolling_folds(
        Period("hist", dt.date(2020, 1, 1), dt.date(2024, 1, 1)),
        train_days=365, validation_days=90, test_days=90,
    )

    assert len(folds) > 1
    for fold in folds:
        assert fold.train.end <= fold.validation.start  # type: ignore[union-attr]
        assert fold.validation.end <= fold.test.start  # type: ignore[union-attr]


def test_each_fold_tests_later_than_the_one_before() -> None:
    folds = rolling_folds(
        Period("hist", dt.date(2020, 1, 1), dt.date(2024, 1, 1)),
        train_days=365, validation_days=60, test_days=60,
    )

    starts = [f.test.start for f in folds]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)


def test_a_fold_whose_test_precedes_training_is_rejected() -> None:
    """The definition of look-ahead, stated as a constructor invariant."""
    with pytest.raises(LeakageError, match="before train ends"):
        Fold(
            index=0,
            train=Period("t", dt.date(2022, 1, 1), dt.date(2023, 1, 1)),
            validation=None,
            test=Period("test", dt.date(2021, 1, 1), dt.date(2021, 6, 1)),
        )


def test_a_fold_whose_test_precedes_validation_is_rejected() -> None:
    with pytest.raises(LeakageError, match="before validation ends"):
        Fold(
            index=0,
            train=Period("t", dt.date(2020, 1, 1), dt.date(2021, 1, 1)),
            validation=Period("v", dt.date(2021, 1, 1), dt.date(2022, 1, 1)),
            test=Period("test", dt.date(2021, 6, 1), dt.date(2021, 12, 1)),
        )


def test_an_anchored_window_grows_while_a_sliding_one_moves() -> None:
    args = dict(train_days=365, validation_days=30, test_days=30)
    period = Period("hist", dt.date(2020, 1, 1), dt.date(2023, 1, 1))

    sliding = rolling_folds(period, **args)  # type: ignore[arg-type]
    anchored = rolling_folds(period, anchored=True, **args)  # type: ignore[arg-type]

    assert sliding[-1].train.start > sliding[0].train.start
    assert all(f.train.start == period.start for f in anchored)
    assert anchored[-1].train.days > anchored[0].train.days


def test_a_period_too_short_for_one_fold_fails_loudly() -> None:
    with pytest.raises(ValueError, match="too short"):
        rolling_folds(
            Period("hist", dt.date(2020, 1, 1), dt.date(2020, 3, 1)),
            train_days=365, validation_days=90, test_days=90,
        )


# -- timestamp alignment --------------------------------------------------------


def test_a_bar_is_not_available_before_its_lag_elapses() -> None:
    """A daily bar stamped at the session date is knowable only after that
    session closes. Treating the stamp as availability is the quietest form
    of look-ahead: nothing looks wrong, the strategy just does better than
    it could have."""
    bar = _bars(1)[0]

    assert available_at(bar) == bar.ts
    assert available_at(bar, publication_lag=dt.timedelta(hours=18)) > bar.ts


def test_publication_lag_pushes_a_bar_out_of_its_period() -> None:
    """A bar stamped on the last day of a window is not usable inside that
    window once a realistic lag is applied."""
    bars = {"AAPL": _bars(40)}
    window = Period("w", START.date(), (START + dt.timedelta(days=10)).date())

    without = slice_bars(bars, window)
    with_lag = slice_bars(bars, window, publication_lag=dt.timedelta(days=1))

    assert len(with_lag["AAPL"]) < len(without["AAPL"])


# -- feature availability -------------------------------------------------------


def test_warmup_bars_come_from_the_past_never_the_future() -> None:
    """An indicator over N bars is unavailable until N bars exist. Borrowing
    them from after the window is how a moving average learns where price is
    going."""
    bars = {"AAPL": _bars(200)}
    window = Period(
        "w",
        (START + dt.timedelta(days=100)).date(),
        (START + dt.timedelta(days=150)).date(),
    )

    sliced = slice_bars(bars, window, warmup_bars=30)

    assert len(sliced["AAPL"]) == 50 + 30
    assert all(b.ts.date() < window.end for b in sliced["AAPL"])
    assert min(b.ts.date() for b in sliced["AAPL"]) < window.start


def test_no_bar_in_a_slice_postdates_its_window() -> None:
    bars = {"AAPL": _bars(200)}
    window = Period("w", START.date(), (START + dt.timedelta(days=50)).date())

    sliced = slice_bars(bars, window, warmup_bars=10)

    assert_no_future_bars(sliced, cutoff=window.end)


def test_a_future_bar_is_caught_rather_than_silently_used() -> None:
    bars = {"AAPL": _bars(200)}

    with pytest.raises(LeakageError, match="cutoff"):
        assert_no_future_bars(bars, cutoff=(START + dt.timedelta(days=10)).date())


def test_slicing_an_empty_window_yields_nothing_not_an_error() -> None:
    bars = {"AAPL": _bars(10)}
    far_future = Period("w", dt.date(2030, 1, 1), dt.date(2030, 2, 1))

    assert slice_bars(bars, far_future) == {}


# -- dataset audit --------------------------------------------------------------


def test_unstated_claims_are_treated_as_unmet() -> None:
    """"We did not check" and "it is fine" must not look the same."""
    audit = audit_dataset({"AAPL": _bars(50)})

    assert not audit.is_clean
    assert any("survivorship" in w for w in audit.warnings())
    assert any("Corporate actions" in w for w in audit.warnings())


def test_a_fully_attested_clean_dataset_passes() -> None:
    audit = audit_dataset(
        {"AAPL": _bars(50)},
        point_in_time_universe=True,
        delisted_included=True,
        corporate_actions_applied=True,
        fundamentals_lagged=True,
    )

    assert audit.is_clean
    assert audit.warnings() == []


def test_duplicate_timestamps_are_detected() -> None:
    bars = _bars(20)
    bars.append(bars[5])

    audit = audit_dataset({"AAPL": bars})

    assert audit.duplicate_timestamps == 1
    assert any("duplicate" in w.lower() for w in audit.warnings())


def test_out_of_order_series_are_detected() -> None:
    bars = _bars(20)
    bars[3], bars[9] = bars[9], bars[3]

    audit = audit_dataset({"AAPL": bars})

    assert "AAPL" in audit.non_monotonic_series


def test_gaps_are_counted_but_are_not_automatically_failures() -> None:
    """Weekends and holidays are gaps too. Counting them is information;
    treating every gap as a defect would make the audit useless."""
    audit = audit_dataset({"AAPL": _bars(20, step_days=10)})

    assert audit.gaps["AAPL"] > 0


def test_survivorship_is_recorded_because_it_cannot_be_fixed_here() -> None:
    """This framework can detect the bias but not remove it. Saying so is
    the difference between a caveat and a lie."""
    warnings = DatasetAudit().warnings()

    assert any("biased upward by survivorship" in w for w in warnings)
    assert any("Delisted" in w for w in warnings)
