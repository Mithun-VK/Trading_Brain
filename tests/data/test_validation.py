from __future__ import annotations

import datetime as dt

from data.ingestion.schemas import PriceBar
from data.normalization.validation import ValidationSeverity, validate_price_bars

NOW = dt.datetime(2026, 1, 10, tzinfo=dt.UTC)


def _bar(
    day: int = 1,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 104.0,
    volume: int = 1000,
) -> PriceBar:
    return PriceBar(
        ts=dt.datetime(2026, 1, day, tzinfo=dt.UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        interval="1d",
        source="test",
    )


def _validate(bars: list[PriceBar]):
    return validate_price_bars(bars, ticker="X", interval="1d", source="test", now=NOW)


def test_clean_bars_pass() -> None:
    report = _validate([_bar(1), _bar(2)])

    assert report.is_clean
    assert len(report.valid_bars) == 2
    assert report.rejected_count == 0


def test_high_below_low_is_rejected() -> None:
    report = _validate([_bar(1, high=90.0, low=95.0)])

    assert not report.is_clean
    assert report.errors[0].code == "high_below_low"
    assert report.valid_bars == []


def test_high_below_body_is_rejected() -> None:
    report = _validate([_bar(1, open_=100.0, close=110.0, high=105.0, low=99.0)])

    assert report.errors[0].code == "high_below_body"


def test_low_above_body_is_rejected() -> None:
    report = _validate([_bar(1, open_=100.0, close=104.0, high=105.0, low=101.0)])

    assert report.errors[0].code == "low_above_body"


def test_non_positive_price_is_rejected() -> None:
    report = _validate([_bar(1, low=0.0)])

    assert report.errors[0].code == "non_positive_price"


def test_nan_value_is_rejected() -> None:
    report = _validate([_bar(1, close=float("nan"))])

    assert report.errors[0].code == "missing_value"


def test_negative_volume_is_rejected() -> None:
    report = _validate([_bar(1, volume=-5)])

    assert report.errors[0].code == "negative_volume"


def test_future_bar_is_rejected() -> None:
    future = PriceBar(
        ts=NOW + dt.timedelta(days=10),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=1,
        interval="1d",
        source="test",
    )

    report = _validate([future])

    assert report.errors[0].code == "future_timestamp"


def test_duplicate_timestamp_keeps_first_only() -> None:
    # Both bars are individually valid, so the only complaint is the collision.
    report = _validate([_bar(1, close=104.0), _bar(1, close=103.0)])

    assert len(report.valid_bars) == 1
    assert report.valid_bars[0].close == 104.0
    assert report.errors[0].code == "duplicate_timestamp"


def test_unordered_bars_are_sorted_and_warned_not_rejected() -> None:
    report = _validate([_bar(3), _bar(1), _bar(2)])

    assert report.is_clean  # a warning, not an error
    assert [bar.ts.day for bar in report.valid_bars] == [1, 2, 3]
    assert report.warnings[0].code == "unordered_timestamps"
    assert report.warnings[0].severity is ValidationSeverity.WARNING


def test_bad_bars_do_not_discard_good_ones() -> None:
    report = _validate([_bar(1), _bar(2, high=1.0, low=500.0), _bar(3)])

    assert len(report.valid_bars) == 2
    assert report.rejected_count == 1
    assert report.bars_checked == 3


def test_empty_input_is_clean() -> None:
    report = _validate([])

    assert report.is_clean
    assert report.valid_bars == []
