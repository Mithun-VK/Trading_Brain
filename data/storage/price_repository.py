"""Incremental, duplicate-safe persistence of OHLCV bars.

`prices` has a unique constraint on (asset_id, ts, interval); this module
makes ingestion idempotent *before* hitting it, so re-running a job is a
no-op rather than an IntegrityError. Timestamps are compared on a
normalized UTC key because SQLite (tests) returns naive datetimes while
PostgreSQL returns aware ones.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.ingestion.schemas import PriceBar
from data.normalization.prices import price_bar_to_model
from models.price import Price


@dataclass(frozen=True)
class UpsertResult:
    inserted: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.skipped


def normalize_ts(value: dt.datetime) -> dt.datetime:
    """Comparable, backend-independent timestamp key (naive UTC)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.UTC).replace(tzinfo=None)


def upsert_price_bars(session: Session, asset_id: int, bars: list[PriceBar]) -> UpsertResult:
    """Insert only bars not already stored. Safe to call repeatedly."""
    if not bars:
        return UpsertResult(inserted=0, skipped=0)

    intervals = {bar.interval for bar in bars}
    existing: set[tuple[str, dt.datetime]] = set()
    for interval in intervals:
        rows = session.scalars(
            select(Price.ts).where(Price.asset_id == asset_id, Price.interval == interval)
        ).all()
        existing.update((interval, normalize_ts(ts)) for ts in rows)

    inserted = 0
    skipped = 0
    seen_in_batch: set[tuple[str, dt.datetime]] = set()

    for bar in bars:
        key = (bar.interval, normalize_ts(bar.ts))
        if key in existing or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)
        session.add(price_bar_to_model(asset_id, bar))
        inserted += 1

    session.flush()
    return UpsertResult(inserted=inserted, skipped=skipped)


def get_latest_bar_ts(session: Session, asset_id: int, interval: str) -> dt.datetime | None:
    """Most recent stored bar timestamp -- the anchor for incremental fetches."""
    return session.scalars(
        select(Price.ts)
        .where(Price.asset_id == asset_id, Price.interval == interval)
        .order_by(Price.ts.desc())
        .limit(1)
    ).first()


def get_price_bars(
    session: Session,
    asset_id: int,
    interval: str = "1d",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int | None = None,
) -> list[Price]:
    query = select(Price).where(Price.asset_id == asset_id, Price.interval == interval)
    if start is not None:
        query = query.where(Price.ts >= start)
    if end is not None:
        query = query.where(Price.ts <= end)
    query = query.order_by(Price.ts.asc())
    rows = list(session.scalars(query).all())
    return rows[-limit:] if limit is not None else rows


def get_close_series(
    session: Session, asset_id: int, interval: str = "1d", limit: int | None = None
) -> list[float]:
    """Chronological closes -- the input shape the quant/regime engines expect."""
    return [float(row.close) for row in get_price_bars(session, asset_id, interval, limit=limit)]
