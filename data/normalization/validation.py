"""Price bar validation.

Corrupted data is never silently accepted: every bar is checked, failures
are recorded as structured `ValidationIssue`s (persisted by
`data.storage.validation_repository`), and only bars that pass every check
reach `ValidationReport.valid_bars`.

Dropping a bad bar is always preferable to repairing it -- an interpolated
price is fabricated data (Rule 4).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from enum import StrEnum

from data.ingestion.schemas import PriceBar

# Providers occasionally stamp a bar slightly ahead of "now" (timezone/rounding).
_FUTURE_TOLERANCE = dt.timedelta(days=1)


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    ts: dt.datetime | None = None


@dataclass
class ValidationReport:
    ticker: str
    interval: str
    source: str
    bars_checked: int = 0
    valid_bars: list[PriceBar] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is ValidationSeverity.WARNING]

    @property
    def is_clean(self) -> bool:
        return not self.errors

    @property
    def rejected_count(self) -> int:
        return self.bars_checked - len(self.valid_bars)


def validate_price_bars(
    bars: list[PriceBar],
    ticker: str,
    interval: str,
    source: str,
    now: dt.datetime | None = None,
) -> ValidationReport:
    now = now or dt.datetime.now(dt.UTC)
    report = ValidationReport(
        ticker=ticker, interval=interval, source=source, bars_checked=len(bars)
    )

    seen_timestamps: set[dt.datetime] = set()
    previous_ts: dt.datetime | None = None
    unordered_reported = False

    for bar in bars:
        issue = _check_bar(bar, now)
        if issue is not None:
            report.issues.append(issue)
            continue

        if bar.ts in seen_timestamps:
            report.issues.append(
                ValidationIssue(
                    code="duplicate_timestamp",
                    message=f"Duplicate bar for {bar.ts.isoformat()} -- keeping the first.",
                    ts=bar.ts,
                )
            )
            continue

        if previous_ts is not None and bar.ts < previous_ts and not unordered_reported:
            unordered_reported = True
            report.issues.append(
                ValidationIssue(
                    code="unordered_timestamps",
                    message="Bars arrived out of chronological order; sorted before use.",
                    severity=ValidationSeverity.WARNING,
                    ts=bar.ts,
                )
            )

        seen_timestamps.add(bar.ts)
        previous_ts = bar.ts
        report.valid_bars.append(bar)

    report.valid_bars.sort(key=lambda b: b.ts)
    return report


def _check_bar(bar: PriceBar, now: dt.datetime) -> ValidationIssue | None:
    values = {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}

    for name, value in values.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ValidationIssue(
                code="missing_value",
                message=f"Bar is missing {name}.",
                ts=bar.ts,
            )
        if value <= 0:
            return ValidationIssue(
                code="non_positive_price",
                message=f"Bar has non-positive {name} ({value}).",
                ts=bar.ts,
            )

    if bar.high < bar.low:
        return ValidationIssue(
            code="high_below_low",
            message=f"high ({bar.high}) is below low ({bar.low}).",
            ts=bar.ts,
        )

    if bar.high < max(bar.open, bar.close):
        return ValidationIssue(
            code="high_below_body",
            message=f"high ({bar.high}) is below open/close ({bar.open}/{bar.close}).",
            ts=bar.ts,
        )

    if bar.low > min(bar.open, bar.close):
        return ValidationIssue(
            code="low_above_body",
            message=f"low ({bar.low}) is above open/close ({bar.open}/{bar.close}).",
            ts=bar.ts,
        )

    if bar.volume < 0:
        return ValidationIssue(
            code="negative_volume",
            message=f"Bar has negative volume ({bar.volume}).",
            ts=bar.ts,
        )

    if bar.ts > now + _FUTURE_TOLERANCE:
        return ValidationIssue(
            code="future_timestamp",
            message=f"Bar is stamped in the future ({bar.ts.isoformat()}).",
            ts=bar.ts,
        )

    return None
