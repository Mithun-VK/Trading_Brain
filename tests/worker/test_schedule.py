from __future__ import annotations

import datetime as dt

from apps.worker.scheduler.schedule import Schedule, ScheduleKind


def _at(hour: int, day: int = 10) -> dt.datetime:
    return dt.datetime(2026, 1, day, hour, 0, tzinfo=dt.UTC)


def test_daily_is_due_when_never_run_and_time_has_passed() -> None:
    schedule = Schedule.daily(at=dt.time(22, 0))

    assert schedule.is_due(_at(22), last_success=None)


def test_daily_is_not_due_before_its_time() -> None:
    schedule = Schedule.daily(at=dt.time(22, 0))

    assert not schedule.is_due(_at(21), last_success=None)


def test_daily_is_not_due_twice_in_one_day() -> None:
    schedule = Schedule.daily(at=dt.time(22, 0))

    assert not schedule.is_due(_at(23), last_success=_at(22))


def test_daily_becomes_due_again_the_next_day() -> None:
    schedule = Schedule.daily(at=dt.time(22, 0))

    assert schedule.is_due(_at(22, day=11), last_success=_at(22, day=10))


def test_daily_still_runs_after_a_missed_day() -> None:
    """A worker that was down must catch up, not skip the window."""
    schedule = Schedule.daily(at=dt.time(22, 0))

    assert schedule.is_due(_at(23, day=15), last_success=_at(22, day=10))


def test_interval_is_due_when_never_run() -> None:
    assert Schedule.interval(every=dt.timedelta(days=7)).is_due(_at(9), last_success=None)


def test_interval_waits_for_the_full_period() -> None:
    schedule = Schedule.interval(every=dt.timedelta(days=7))

    assert not schedule.is_due(_at(9, day=12), last_success=_at(9, day=10))
    assert schedule.is_due(_at(9, day=17), last_success=_at(9, day=10))


def test_manual_schedule_is_never_automatically_due() -> None:
    schedule = Schedule.manual()

    assert not schedule.is_due(_at(9), last_success=None)
    assert schedule.kind is ScheduleKind.MANUAL


def test_naive_stored_timestamps_are_compared_safely() -> None:
    """SQLite returns naive datetimes; comparing them to aware `now` must not raise."""
    schedule = Schedule.daily(at=dt.time(22, 0))
    naive_last_run = dt.datetime(2026, 1, 10, 22, 0)

    assert schedule.is_due(_at(22, day=11), last_success=naive_last_run)
    assert not schedule.is_due(_at(23, day=10), last_success=naive_last_run)


def test_describe_is_human_readable() -> None:
    assert "daily" in Schedule.daily(at=dt.time(22, 0)).describe()
    assert "every" in Schedule.interval(every=dt.timedelta(days=1)).describe()
    assert "manual" in Schedule.manual().describe()
