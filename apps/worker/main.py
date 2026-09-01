"""TradingBrain worker entrypoint.

Placeholder for background/scheduled jobs (data ingestion, regime detection,
periodic research refresh). Intentionally does nothing yet in Phase 0 beyond
proving the process boots and can reach configuration/logging — real jobs
land in later phases (data ingestion in Phase 3-4, regime detection in
Phase 6).
"""

from __future__ import annotations

from config.logging import configure_logging, get_logger

configure_logging()
logger = get_logger("worker")


def main() -> None:
    logger.info("worker_startup", operation="main", status="ready")


if __name__ == "__main__":
    main()
