"""Cost governance: budgets, rate limiting, and request deduplication.

These run *before* a provider is invoked, in that order, because each can end
a request more cheaply than the next. A limiter that runs after context
assembly has already paid for the work it was meant to prevent.

The budget is checked against a **projection that assumes maximum output**.
Under-estimating and discovering afterwards that you exceeded the ceiling is
not a budget.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from ai.schemas import AICost, AIResponse
from config.logging import get_logger

logger = get_logger("ai")


class BudgetState(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"  # past the warn ratio; router prefers cheaper tiers
    EXCEEDED = "exceeded"  # blocked


@dataclass(frozen=True)
class BudgetVerdict:
    state: BudgetState
    reason: str
    window: str | None = None
    spent: float | None = None
    limit: float | None = None

    @property
    def allowed(self) -> bool:
        return self.state is not BudgetState.EXCEEDED

    def to_dict(self) -> dict[str, object]:
        return {
            "state": str(self.state),
            "reason": self.reason,
            "window": self.window,
            "spent": self.spent,
            "limit": self.limit,
        }


@dataclass
class _Window:
    name: str
    duration: dt.timedelta | None  # None = calendar month
    limit: float
    entries: deque[tuple[dt.datetime, float]] = field(default_factory=deque)

    def prune(self, now: dt.datetime) -> None:
        if self.duration is not None:
            cutoff = now - self.duration
            while self.entries and self.entries[0][0] < cutoff:
                self.entries.popleft()
            return
        # Calendar month: drop anything from a previous month.
        while self.entries and (
            self.entries[0][0].year,
            self.entries[0][0].month,
        ) != (now.year, now.month):
            self.entries.popleft()

    def spent(self, now: dt.datetime) -> float:
        self.prune(now)
        return sum(amount for _, amount in self.entries)


class BudgetLedger:
    """In-process spend accounting.

    Deliberately in-memory and per-process: it is a fast pre-flight guard,
    not the system of record. The durable record is the `ai_requests` table,
    and `/ai/budget` reads spend from there. A single-operator deployment
    runs one API process, so the two agree; a multi-process deployment would
    need this backed by Redis, which is recorded as a known limitation in
    docs/ai-gateway.md rather than pretended away.
    """

    def __init__(
        self,
        *,
        per_request: float = 0.0,
        per_hour: float = 0.0,
        per_day: float = 0.0,
        per_month: float = 0.0,
        warn_ratio: float = 0.8,
    ) -> None:
        self._per_request = per_request
        self._warn_ratio = warn_ratio
        self._lock = threading.Lock()
        self._windows = [
            w
            for w in (
                _Window("hour", dt.timedelta(hours=1), per_hour),
                _Window("day", dt.timedelta(days=1), per_day),
                _Window("month", None, per_month),
            )
            if w.limit > 0
        ]

    def check(self, projected: AICost, now: dt.datetime | None = None) -> BudgetVerdict:
        now = now or dt.datetime.now(dt.UTC)

        if not projected.known or projected.amount is None:
            # An unpriced model cannot be budgeted. The gateway decides what
            # to do with that via AI_ALLOW_UNPRICED_MODELS; the ledger's job
            # is to say plainly that it does not know.
            return BudgetVerdict(
                state=BudgetState.HEALTHY,
                reason=(
                    "Cost could not be projected (unpriced model); this request "
                    "is not counted against any budget."
                ),
            )

        amount = projected.amount

        if self._per_request > 0 and amount > self._per_request:
            return BudgetVerdict(
                state=BudgetState.EXCEEDED,
                reason=(
                    f"Projected cost {amount:.4f} exceeds the per-request ceiling "
                    f"of {self._per_request:.4f}."
                ),
                window="request",
                spent=amount,
                limit=self._per_request,
            )

        with self._lock:
            for window in self._windows:
                spent = window.spent(now)
                if spent + amount > window.limit:
                    return BudgetVerdict(
                        state=BudgetState.EXCEEDED,
                        reason=(
                            f"Projected spend would exceed the {window.name} budget "
                            f"({spent:.4f} + {amount:.4f} > {window.limit:.4f})."
                        ),
                        window=window.name,
                        spent=spent,
                        limit=window.limit,
                    )

            for window in self._windows:
                spent = window.spent(now)
                if spent + amount > window.limit * self._warn_ratio:
                    return BudgetVerdict(
                        state=BudgetState.WARNING,
                        reason=(
                            f"Approaching the {window.name} budget "
                            f"({spent:.4f} of {window.limit:.4f})."
                        ),
                        window=window.name,
                        spent=spent,
                        limit=window.limit,
                    )

        return BudgetVerdict(state=BudgetState.HEALTHY, reason="Within budget.")

    def record(self, cost: AICost, now: dt.datetime | None = None) -> None:
        """Record actual spend. Unknown costs are not recorded as zero -- they
        are simply not recorded, and the audit row preserves that fact."""
        if not cost.known or cost.amount is None:
            return
        now = now or dt.datetime.now(dt.UTC)
        with self._lock:
            for window in self._windows:
                window.entries.append((now, cost.amount))

    def snapshot(self, now: dt.datetime | None = None) -> list[dict[str, object]]:
        now = now or dt.datetime.now(dt.UTC)
        with self._lock:
            return [
                {
                    "window": w.name,
                    "limit": w.limit,
                    "spent": round(w.spent(now), 6),
                    "remaining": round(max(0.0, w.limit - w.spent(now)), 6),
                }
                for w in self._windows
            ]


# --- rate limiting -----------------------------------------------------------


@dataclass(frozen=True)
class RateVerdict:
    allowed: bool
    reason: str
    retry_after_seconds: float | None = None


class RateLimiter:
    """Sliding-window limiter keyed by caller.

    Keys are (principal, dimension) so one client cannot exhaust another's
    allowance -- an unkeyed global limiter turns one noisy caller into a
    denial of service for everyone.
    """

    def __init__(self, *, per_minute: int = 0, per_hour: int = 0) -> None:
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._lock = threading.Lock()
        self._hits: dict[str, deque[dt.datetime]] = {}

    def check(self, key: str, now: dt.datetime | None = None) -> RateVerdict:
        now = now or dt.datetime.now(dt.UTC)
        if self._per_minute <= 0 and self._per_hour <= 0:
            return RateVerdict(True, "Rate limiting disabled.")

        with self._lock:
            hits = self._hits.setdefault(key, deque())
            cutoff = now - dt.timedelta(hours=1)
            while hits and hits[0] < cutoff:
                hits.popleft()

            if self._per_hour > 0 and len(hits) >= self._per_hour:
                return RateVerdict(
                    False,
                    f"Hourly AI request limit of {self._per_hour} reached.",
                    retry_after_seconds=_seconds_until(hits[0] + dt.timedelta(hours=1), now),
                )

            minute_cutoff = now - dt.timedelta(minutes=1)
            recent = [h for h in hits if h >= minute_cutoff]
            if self._per_minute > 0 and len(recent) >= self._per_minute:
                return RateVerdict(
                    False,
                    f"Per-minute AI request limit of {self._per_minute} reached.",
                    retry_after_seconds=_seconds_until(
                        recent[0] + dt.timedelta(minutes=1), now
                    ),
                )

        return RateVerdict(True, "Within rate limits.")

    def record(self, key: str, now: dt.datetime | None = None) -> None:
        now = now or dt.datetime.now(dt.UTC)
        with self._lock:
            self._hits.setdefault(key, deque()).append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def _seconds_until(when: dt.datetime, now: dt.datetime) -> float:
    return max(0.0, round((when - now).total_seconds(), 2))


# --- deduplication and caching -----------------------------------------------


@dataclass
class _CacheEntry:
    response: AIResponse
    expires_at: dt.datetime


class ResponseCache:
    """Short-lived cache keyed by request fingerprint.

    Deliberately short by default. These responses are reasoning *about
    market evidence*, and evidence goes stale -- serving a cached thesis
    review after the price has moved would present old reasoning as current.
    Task-specific TTLs let long-lived work (a journal review over closed
    trades) cache longer than volatile work.
    """

    def __init__(self, *, default_ttl_seconds: int = 900) -> None:
        self._default_ttl = default_ttl_seconds
        self._entries: dict[str, _CacheEntry] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    def get(self, fingerprint: str, now: dt.datetime | None = None) -> AIResponse | None:
        now = now or dt.datetime.now(dt.UTC)
        with self._lock:
            entry = self._entries.get(fingerprint)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[fingerprint]
                return None
            return entry.response

    def put(
        self,
        fingerprint: str,
        response: AIResponse,
        *,
        ttl_seconds: int | None = None,
        now: dt.datetime | None = None,
    ) -> None:
        # Never cache a failure. A transient outage must not become a
        # 15-minute outage for every caller asking the same question.
        if not response.success:
            return
        now = now or dt.datetime.now(dt.UTC)
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        with self._lock:
            self._entries[fingerprint] = _CacheEntry(
                response=response, expires_at=now + dt.timedelta(seconds=ttl)
            )

    def begin(self, fingerprint: str) -> bool:
        """Claim a fingerprint. False means an identical request is already
        running, so the caller should not start a second one."""
        with self._lock:
            if fingerprint in self._in_flight:
                return False
            self._in_flight.add(fingerprint)
            return True

    def end(self, fingerprint: str) -> None:
        with self._lock:
            self._in_flight.discard(fingerprint)

    def stats(self, now: dt.datetime | None = None) -> dict[str, int]:
        now = now or dt.datetime.now(dt.UTC)
        with self._lock:
            live = sum(1 for e in self._entries.values() if e.expires_at > now)
            return {"entries": live, "in_flight": len(self._in_flight)}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._in_flight.clear()


# Per-task cache lifetimes, in seconds. Reasoning over closed, immutable
# records can be cached far longer than reasoning over live market state.
TASK_CACHE_TTL: dict[str, int] = {
    "journal_review": 3600,  # closed trades do not change
    "summarization": 3600,
    "classification": 3600,
    "entity_extraction": 3600,
    "research_synthesis": 600,  # evidence moves
    "thesis_review": 300,  # the most time-sensitive reasoning here
}
