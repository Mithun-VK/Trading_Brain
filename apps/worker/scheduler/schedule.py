"""Schedule definitions.

Deliberately dependency-free (no APScheduler/Celery): `is_due()` is a pure
function of `now` and the job's last successful run, which makes scheduling
deterministic and unit-testable without sleeping or patching the clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum


class ScheduleKind(StrEnum):
    DAILY = "daily"
    INTERVAL = "interval"
    MANUAL = "manual"


@dataclass(frozen=True)
class Schedule:
    kind: ScheduleKind
    at: dt.time | None = None
    every: dt.timedelta | None = None

    @classmethod
    def daily(cls, at: dt.time) -> Schedule:
        """Run once per calendar day, at or after `at` (UTC)."""
        return cls(kind=ScheduleKind.DAILY, at=at)

    @classmethod
    def interval(cls, every: dt.timedelta) -> Schedule:
        return cls(kind=ScheduleKind.INTERVAL, every=every)

    @classmethod
    def manual(cls) -> Schedule:
        """Never runs automatically -- only via an explicit trigger."""
        return cls(kind=ScheduleKind.MANUAL)

    def is_due(self, now: dt.datetime, last_success: dt.datetime | None) -> bool:
        if self.kind is ScheduleKind.MANUAL:
            return False

        if self.kind is ScheduleKind.INTERVAL:
            if self.every is None:
                return False
            if last_success is None:
                return True
            return (now - _aware(last_success, now)) >= self.every

        # DAILY
        if self.at is not None and now.timetz().replace(tzinfo=None) < self.at:
            return False
        if last_success is None:
            return True
        return _aware(last_success, now).date() < now.date()

    def describe(self) -> str:
        if self.kind is ScheduleKind.DAILY:
            return f"daily at {self.at.isoformat() if self.at else '00:00'} UTC"
        if self.kind is ScheduleKind.INTERVAL:
            return f"every {self.every}"
        return "manual only"


def _aware(value: dt.datetime, reference: dt.datetime) -> dt.datetime:
    """Align a stored timestamp with `reference`'s awareness.

    SQLite returns naive datetimes while PostgreSQL returns aware ones;
    comparing the two directly raises, so normalize before arithmetic.
    """
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
