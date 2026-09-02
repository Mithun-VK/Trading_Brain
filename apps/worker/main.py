"""TradingBrain worker entrypoint.

Usage:
    python -m apps.worker.main list              # show registered jobs
    python -m apps.worker.main run <job_name>    # manual trigger
    python -m apps.worker.main run-due           # run everything currently due
    python -m apps.worker.main loop [--interval N]   # poll for due jobs

The loop deliberately polls rather than holding an in-process timer: due-ness
is derived from the `job_runs` table, so a restarted (or replaced) worker
picks up exactly where the previous one left off.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from apps.worker.jobs.base import JobContext, JobTrigger
from apps.worker.jobs.company_update import CompanyUpdateJob
from apps.worker.jobs.daily_market import DailyMarketUpdateJob
from apps.worker.jobs.learning_review import LearningReviewJob
from apps.worker.jobs.portfolio_update import PortfolioUpdateJob
from apps.worker.jobs.reporting import DailyReportJob, MonthlyReportJob, WeeklyReportJob
from apps.worker.jobs.research_refresh import ResearchRefreshJob
from apps.worker.scheduler.schedule import Schedule
from apps.worker.scheduler.scheduler import JobScheduler
from config.logging import configure_logging, get_logger
from config.settings import get_settings
from data.ingestion.factory import build_registry
from data.storage.session import session_scope
from integrations.obsidian.errors import ObsidianError
from integrations.obsidian.obsidian_knowledge_store import ObsidianKnowledgeStore

configure_logging()
logger = get_logger("worker")

DEFAULT_POLL_SECONDS = 300


def build_scheduler() -> JobScheduler:
    """The production job schedule. Times are UTC."""
    scheduler = JobScheduler()
    scheduler.register(DailyMarketUpdateJob(), Schedule.daily(at=dt.time(hour=22, minute=0)))
    scheduler.register(CompanyUpdateJob(), Schedule.interval(every=dt.timedelta(days=7)))
    # Snapshots after prices land, so equity reflects the day just ingested.
    scheduler.register(PortfolioUpdateJob(), Schedule.daily(at=dt.time(hour=22, minute=30)))
    # Runs after the daily price update so it scores against fresh data.
    scheduler.register(ResearchRefreshJob(), Schedule.daily(at=dt.time(hour=23, minute=0)))
    # Reports run last, so they describe a fully-updated day.
    scheduler.register(DailyReportJob(), Schedule.daily(at=dt.time(hour=23, minute=30)))
    scheduler.register(WeeklyReportJob(), Schedule.interval(every=dt.timedelta(days=7)))
    scheduler.register(MonthlyReportJob(), Schedule.interval(every=dt.timedelta(days=30)))
    # Monthly: enough outcomes need to resolve before a review says anything.
    scheduler.register(LearningReviewJob(), Schedule.interval(every=dt.timedelta(days=30)))
    return scheduler


def _knowledge_store():
    """Obsidian is optional: jobs that need it SKIP when it is absent."""
    settings = get_settings()
    if not settings.obsidian_api_key:
        return None
    try:
        return ObsidianKnowledgeStore(settings)
    except ObsidianError as exc:
        logger.warning("obsidian_unavailable", operation="startup", status="degraded",
                       error=type(exc).__name__)
        return None


def _context(session, now: dt.datetime | None = None) -> JobContext:
    return JobContext(
        session=session,
        now=now or dt.datetime.now(dt.UTC),
        registry=build_registry(),
        knowledge_store=_knowledge_store(),
    )


def _cmd_list(scheduler: JobScheduler) -> int:
    for name, schedule in scheduler.describe().items():
        print(f"{name:<24} {schedule}")
    return 0


def _cmd_run(scheduler: JobScheduler, job_name: str) -> int:
    with session_scope() as session:
        result = scheduler.run_job(job_name, _context(session), trigger=JobTrigger.MANUAL)
    print(f"{result.job_name}: {result.status} ({result.items_processed} items)")
    if result.error:
        print(f"  error: {result.error}")
    return 0 if result.ok else 1


def _cmd_run_due(scheduler: JobScheduler) -> int:
    with session_scope() as session:
        results = scheduler.run_due(_context(session))
    if not results:
        print("Nothing due.")
        return 0
    for result in results:
        print(f"{result.job_name}: {result.status} ({result.items_processed} items)")
    return 0 if all(r.ok for r in results) else 1


def _cmd_loop(scheduler: JobScheduler, poll_seconds: int) -> int:
    logger.info("worker_loop_start", operation="loop", status="ready", poll_seconds=poll_seconds)
    while True:
        try:
            with session_scope() as session:
                scheduler.run_due(_context(session))
        except Exception as exc:  # noqa: BLE001 -- the loop must survive a bad cycle
            logger.warning("worker_loop_error", operation="loop", status="error", error=str(exc))
        time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradingbrain-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered jobs and their schedules")
    run_parser = subparsers.add_parser("run", help="Run a single job now")
    run_parser.add_argument("job_name")
    subparsers.add_parser("run-due", help="Run every job that is currently due")
    loop_parser = subparsers.add_parser("loop", help="Poll continuously for due jobs")
    loop_parser.add_argument("--interval", type=int, default=DEFAULT_POLL_SECONDS)

    args = parser.parse_args(argv)
    scheduler = build_scheduler()

    if args.command == "list":
        return _cmd_list(scheduler)
    if args.command == "run":
        return _cmd_run(scheduler, args.job_name)
    if args.command == "run-due":
        return _cmd_run_due(scheduler)
    if args.command == "loop":
        return _cmd_loop(scheduler, args.interval)
    return 1


if __name__ == "__main__":
    sys.exit(main())
