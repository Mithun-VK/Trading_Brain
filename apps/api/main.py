"""TradingBrain API entrypoint.

FastAPI application factory. No broker execution routes exist or will
exist in this phase — see the guard below.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from apps.api.routers import (
    analysis,
    assets,
    backtests,
    health,
    learning,
    market,
    paper_trades,
    portfolio,
    research,
    research_queue,
    signals,
    thesis,
    trades,
    watchlists,
)
from config.logging import configure_logging, get_logger
from config.settings import get_settings

configure_logging()
logger = get_logger("api")

# Rule 8: no live broker integration in these phases. This is a defense-in-depth
# guard, not the primary control — the primary control is that no such router
# is ever registered.
_BLOCKED_PATH_PREFIXES = ("/orders", "/execute", "/buy", "/sell")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TradingBrain API",
        version="0.1.0",
        description="Orchestration layer for TradingBrain. Research and analysis only — "
        "no broker execution in this phase.",
    )

    @app.middleware("http")
    async def block_execution_endpoints(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if any(request.url.path.startswith(p) for p in _BLOCKED_PATH_PREFIXES):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Broker execution endpoints are disabled in this phase "
                    "of TradingBrain (Rule 8)."
                },
            )
        return await call_next(request)

    @app.middleware("http")
    async def request_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            request_id=request_id,
            operation=f"{request.method} {request.url.path}",
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router)
    app.include_router(assets.router)
    app.include_router(market.router)
    app.include_router(analysis.router)
    app.include_router(research.router)
    app.include_router(thesis.router)
    app.include_router(trades.router)
    app.include_router(portfolio.router)
    app.include_router(watchlists.router)
    app.include_router(signals.router)
    app.include_router(research_queue.router)
    app.include_router(backtests.router)
    app.include_router(paper_trades.router)
    app.include_router(learning.router)

    logger.info("api_startup", operation="create_app", status="ready", app_env=settings.app_env)
    return app


app = create_app()
