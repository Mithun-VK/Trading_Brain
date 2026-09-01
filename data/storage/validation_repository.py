from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.normalization.validation import ValidationReport
from models.data_validation_error import DataValidationError


def save_validation_report(
    session: Session, report: ValidationReport, asset_id: int | None = None
) -> int:
    """Persist every issue in a report. Returns how many rows were written."""
    for issue in report.issues:
        session.add(
            DataValidationError(
                asset_id=asset_id,
                ticker=report.ticker,
                interval=report.interval,
                source=report.source,
                code=issue.code,
                severity=str(issue.severity),
                message=issue.message,
                bar_ts=issue.ts,
            )
        )
    session.flush()
    return len(report.issues)


def get_recent_validation_errors(
    session: Session, ticker: str | None = None, limit: int = 50
) -> list[DataValidationError]:
    query = select(DataValidationError).order_by(DataValidationError.created_at.desc())
    if ticker:
        query = query.where(DataValidationError.ticker == ticker)
    return list(session.scalars(query.limit(limit)).all())
