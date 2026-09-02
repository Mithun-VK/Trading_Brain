"""Health checks.

Design rule, stated because it is easy to get wrong: **a process that is
running is not a healthy system.** `/health` aggregates real dependency and
data checks, so a reachable API with a dead database, stale prices, or a
failing scheduler reports DEGRADED or UNAVAILABLE — not OK.

Three states, and the distinction matters operationally:
- `HEALTHY`    — working as intended
- `DEGRADED`   — functioning with reduced capability or confidence
                 (stale data, an optional integration unconfigured)
- `UNAVAILABLE`— a required capability is broken

An **unconfigured optional** integration (Obsidian, Claude) is DEGRADED,
not UNAVAILABLE: the system genuinely works without it, and calling that a
failure would train you to ignore health output.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from models.job_run import JobRun
from models.paper_portfolio import PaperPortfolio, PaperTransaction
from models.price import Price
from models.research_queue import ResearchQueueEntry
from models.thesis import Thesis
from models.watchlist import Watchlist

# Thresholds. Configuration, not scattered magic numbers.
PRICE_STALE_DAYS = 4  # a long weekend plus a holiday
PRICE_CRITICAL_DAYS = 10
THESIS_STALE_DAYS = 60
QUEUE_STALE_DAYS = 14
JOB_FAILURE_WINDOW_HOURS = 48
# A health probe must fail fast; it is not doing real work.
OBSIDIAN_PROBE_TIMEOUT = 2.0


class Status(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


_SEVERITY = {Status.HEALTHY: 0, Status.DEGRADED: 1, Status.UNAVAILABLE: 2}


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": str(self.status),
            "detail": self.detail,
            **({"data": self.data} if self.data else {}),
        }


def aggregate(checks: list[Check]) -> Status:
    """Worst status wins. Averaging health would hide the one broken thing."""
    if not checks:
        return Status.HEALTHY
    return max(checks, key=lambda c: _SEVERITY[c.status]).status


def _age_days(value: dt.datetime | None, now: dt.datetime) -> float | None:
    if value is None:
        return None
    stamp = value if value.tzinfo else value.replace(tzinfo=now.tzinfo)
    return round((now - stamp).total_seconds() / 86400, 2)


# -- dependency checks --------------------------------------------------------


def check_database(session: Session) -> Check:
    try:
        session.execute(select(1))
    except Exception as exc:  # noqa: BLE001 -- a health check must not raise
        return Check(
            name="database",
            status=Status.UNAVAILABLE,
            detail=f"Database query failed: {type(exc).__name__}",
        )
    return Check(name="database", status=Status.HEALTHY, detail="Query succeeded.")


def check_obsidian(settings: Settings | None = None) -> Check:
    settings = settings or get_settings()
    if not settings.obsidian_api_key:
        return Check(
            name="obsidian",
            status=Status.DEGRADED,
            detail="Not configured. Knowledge-store features are unavailable.",
        )

    # A direct, single-shot probe rather than the KnowledgeStore: that class
    # retries three times with backoff, which is right for real work and
    # wrong for a health check. A probe must fail fast.
    import httpx

    from integrations.obsidian.obsidian_knowledge_store import _tls_verification

    try:
        response = httpx.get(
            f"{settings.obsidian_base_url.rstrip('/')}/vault/",
            headers={"Authorization": f"Bearer {settings.obsidian_api_key}"},
            timeout=OBSIDIAN_PROBE_TIMEOUT,
            verify=_tls_verification(settings),
        )
    except Exception as exc:  # noqa: BLE001 -- a health check must not raise
        return Check(
            name="obsidian",
            status=Status.UNAVAILABLE,
            detail=f"Configured but unreachable: {type(exc).__name__}",
        )

    if response.status_code in (401, 403):
        return Check(
            name="obsidian",
            status=Status.UNAVAILABLE,
            detail="Vault reachable but the API key was rejected.",
        )
    if response.status_code >= 400:
        return Check(
            name="obsidian",
            status=Status.DEGRADED,
            detail=f"Vault responded {response.status_code}.",
        )
    return Check(name="obsidian", status=Status.HEALTHY, detail="Vault reachable.")


def check_claude(settings: Settings | None = None) -> Check:
    """Configuration check only.

    Deliberately does NOT call the API: a health endpoint that bills you per
    poll is a bad health endpoint. Reachability surfaces through job
    failures instead.
    """
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        return Check(
            name="claude",
            status=Status.DEGRADED,
            detail="ANTHROPIC_API_KEY not set. Research/thesis agents unavailable.",
        )
    return Check(
        name="claude",
        status=Status.HEALTHY,
        detail=f"Configured (model: {settings.anthropic_model}). Not probed.",
        data={"model": settings.anthropic_model},
    )


def check_market_data(settings: Settings | None = None) -> Check:
    """Provider configuration and health.

    A synthetic primary in production is DEGRADED: the system runs, but the
    numbers are generated (Rule 4).
    """
    settings = settings or get_settings()
    from data.ingestion.errors import ProviderError
    from data.ingestion.factory import build_registry

    try:
        registry = build_registry(settings)
    except ProviderError as exc:
        return Check(
            name="market_data",
            status=Status.UNAVAILABLE,
            detail=f"Provider registry could not be built: {exc}",
        )

    primary = registry.primary
    synthetic = registry.is_synthetic(primary)
    data = {
        "primary": primary,
        "synthetic": synthetic,
        "fallbacks": registry.fallbacks,
    }

    if synthetic and settings.is_production:
        return Check(
            name="market_data",
            status=Status.DEGRADED,
            detail=(
                f"Primary provider {primary!r} is synthetic while APP_ENV is "
                "production. Generated data must never be mistaken for real."
            ),
            data=data,
        )
    if synthetic:
        return Check(
            name="market_data",
            status=Status.HEALTHY,
            detail=f"Using synthetic provider {primary!r} (non-production).",
            data=data,
        )

    health = registry.health_check(primary)
    if not health.healthy:
        return Check(
            name="market_data",
            status=Status.UNAVAILABLE,
            detail=f"Primary provider {primary!r} failed its probe: {health.error}",
            data=data,
        )
    return Check(
        name="market_data",
        status=Status.HEALTHY,
        detail=f"Provider {primary!r} reachable.",
        data={**data, "latency_ms": health.latency_ms},
    )


def dependency_checks(session: Session, settings: Settings | None = None) -> list[Check]:
    settings = settings or get_settings()
    return [
        check_database(session),
        check_market_data(settings),
        check_obsidian(settings),
        check_claude(settings),
    ]


# -- data checks --------------------------------------------------------------


def check_price_freshness(session: Session, now: dt.datetime) -> Check:
    latest = session.scalars(select(func.max(Price.ts))).first()
    if latest is None:
        return Check(
            name="price_freshness",
            status=Status.DEGRADED,
            detail="No price data stored. Run the daily_market_update job.",
        )

    age = _age_days(latest, now) or 0.0
    data = {"latest_bar": str(latest), "age_days": age}
    if age > PRICE_CRITICAL_DAYS:
        return Check(
            name="price_freshness",
            status=Status.UNAVAILABLE,
            detail=f"Newest price bar is {age:.1f} days old; analysis would be stale.",
            data=data,
        )
    if age > PRICE_STALE_DAYS:
        return Check(
            name="price_freshness",
            status=Status.DEGRADED,
            detail=f"Newest price bar is {age:.1f} days old.",
            data=data,
        )
    return Check(
        name="price_freshness",
        status=Status.HEALTHY,
        detail=f"Newest price bar is {age:.1f} days old.",
        data=data,
    )


def check_stale_theses(session: Session, now: dt.datetime) -> Check:
    theses = list(
        session.scalars(select(Thesis).where(Thesis.status == "active")).all()
    )
    if not theses:
        return Check(
            name="stale_theses", status=Status.HEALTHY, detail="No active theses."
        )

    stale = [
        t
        for t in theses
        if (age := _age_days(t.last_reviewed_at, now)) is None or age > THESIS_STALE_DAYS
    ]
    if stale:
        return Check(
            name="stale_theses",
            status=Status.DEGRADED,
            detail=(
                f"{len(stale)} of {len(theses)} active theses unreviewed for over "
                f"{THESIS_STALE_DAYS} days."
            ),
            data={"stale": [t.title for t in stale[:10]]},
        )
    return Check(
        name="stale_theses",
        status=Status.HEALTHY,
        detail=f"All {len(theses)} active theses reviewed recently.",
    )


def check_research_queue_age(session: Session, now: dt.datetime) -> Check:
    pending = list(
        session.scalars(
            select(ResearchQueueEntry).where(ResearchQueueEntry.status == "pending")
        ).all()
    )
    if not pending:
        return Check(
            name="research_queue", status=Status.HEALTHY, detail="Queue is empty."
        )

    ages = [_age_days(e.detected_at, now) or 0.0 for e in pending]
    oldest = max(ages)
    if oldest > QUEUE_STALE_DAYS:
        return Check(
            name="research_queue",
            status=Status.DEGRADED,
            detail=(
                f"{len(pending)} pending items; oldest is {oldest:.1f} days old. "
                "Research is falling behind detection."
            ),
            data={"pending": len(pending), "oldest_days": oldest},
        )
    return Check(
        name="research_queue",
        status=Status.HEALTHY,
        detail=f"{len(pending)} pending items; oldest {oldest:.1f} days.",
        data={"pending": len(pending), "oldest_days": oldest},
    )


def check_watchlists(session: Session) -> Check:
    watchlists = list(session.scalars(select(Watchlist)).all())
    if not watchlists:
        return Check(
            name="watchlists",
            status=Status.DEGRADED,
            detail="No watchlists configured; research and signals have no focus.",
        )
    empty = [w.name for w in watchlists if not w.items]
    if empty:
        return Check(
            name="watchlists",
            status=Status.DEGRADED,
            detail=f"{len(empty)} watchlist(s) contain no assets.",
            data={"empty": empty[:10]},
        )
    return Check(
        name="watchlists",
        status=Status.HEALTHY,
        detail=f"{len(watchlists)} watchlist(s) configured.",
    )


def check_portfolio_consistency(session: Session) -> Check:
    """Cash must equal initial cash plus the sum of ledger movements.

    The ledger is the source of truth; a mismatch means state drifted from
    its own audit trail, which is a correctness bug, not a warning.
    """
    portfolios = list(session.scalars(select(PaperPortfolio)).all())
    if not portfolios:
        return Check(
            name="portfolio_consistency",
            status=Status.HEALTHY,
            detail="No paper portfolios configured.",
        )

    mismatches = []
    for portfolio in portfolios:
        transactions = session.scalars(
            select(PaperTransaction).where(
                PaperTransaction.portfolio_id == portfolio.id
            )
        ).all()
        expected = float(portfolio.initial_cash) + sum(
            float(t.cash_delta) for t in transactions
        )
        actual = float(portfolio.cash_balance)
        if abs(expected - actual) > 0.01:
            mismatches.append(
                {"portfolio": portfolio.name, "expected": round(expected, 2),
                 "actual": round(actual, 2)}
            )

    if mismatches:
        return Check(
            name="portfolio_consistency",
            status=Status.UNAVAILABLE,
            detail="Cash balance does not reconcile with the transaction ledger.",
            data={"mismatches": mismatches},
        )
    return Check(
        name="portfolio_consistency",
        status=Status.HEALTHY,
        detail=f"{len(portfolios)} portfolio(s) reconcile with their ledgers.",
    )


def data_checks(session: Session, now: dt.datetime | None = None) -> list[Check]:
    now = now or dt.datetime.now(dt.UTC)
    return [
        check_price_freshness(session, now),
        check_portfolio_consistency(session),
        check_stale_theses(session, now),
        check_research_queue_age(session, now),
        check_watchlists(session),
    ]


# -- job checks ---------------------------------------------------------------


def job_checks(session: Session, now: dt.datetime | None = None) -> list[Check]:
    """Scheduler health, derived from the job_runs audit trail."""
    now = now or dt.datetime.now(dt.UTC)
    runs = list(
        session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(200)).all()
    )
    if not runs:
        return [
            Check(
                name="scheduler",
                status=Status.DEGRADED,
                detail="No job has ever run. Is the worker running?",
            )
        ]

    checks: list[Check] = []
    last_run_age = _age_days(runs[0].started_at, now) or 0.0
    checks.append(
        Check(
            name="scheduler",
            status=Status.DEGRADED if last_run_age > 2 else Status.HEALTHY,
            detail=f"Last job ran {last_run_age:.1f} days ago.",
            data={"last_run_days": last_run_age, "last_job": runs[0].job_name},
        )
    )

    cutoff = now - dt.timedelta(hours=JOB_FAILURE_WINDOW_HOURS)
    recent = [
        r
        for r in runs
        if (r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=now.tzinfo))
        >= cutoff
    ]
    failures = [r for r in recent if r.status == "failed"]

    # Only the *latest* run per job matters: a job that failed then
    # succeeded on retry is not currently broken.
    latest_by_job: dict[str, JobRun] = {}
    for run in runs:
        latest_by_job.setdefault(run.job_name, run)
    currently_failing = [name for name, run in latest_by_job.items() if run.status == "failed"]

    if currently_failing:
        status = Status.UNAVAILABLE
        detail = f"Jobs currently failing: {', '.join(sorted(currently_failing))}."
    elif failures:
        status = Status.DEGRADED
        detail = (
            f"{len(failures)} failed attempt(s) in the last "
            f"{JOB_FAILURE_WINDOW_HOURS}h, but all jobs have since succeeded."
        )
    else:
        status = Status.HEALTHY
        detail = f"No job failures in the last {JOB_FAILURE_WINDOW_HOURS}h."

    checks.append(
        Check(
            name="job_failures",
            status=status,
            detail=detail,
            data={
                "recent_failures": len(failures),
                "currently_failing": sorted(currently_failing),
                "jobs_seen": sorted(latest_by_job),
            },
        )
    )
    return checks


def full_health(session: Session, now: dt.datetime | None = None) -> dict:
    """Everything, aggregated. This is what `/health` reports."""
    now = now or dt.datetime.now(dt.UTC)
    settings = get_settings()
    dependencies = dependency_checks(session, settings)
    data = data_checks(session, now)
    jobs = job_checks(session, now)
    everything = dependencies + data + jobs

    return {
        "status": str(aggregate(everything)),
        "app_env": settings.app_env,
        "checked_at": now.isoformat(),
        "dependencies": str(aggregate(dependencies)),
        "data": str(aggregate(data)),
        "jobs": str(aggregate(jobs)),
        "checks": [c.to_dict() for c in everything],
    }
