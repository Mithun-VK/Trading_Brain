"""Usage accounting and aggregation.

Before this existed, the Anthropic SDK returned token counts on every call
and TradingBrain discarded them on every call -- so the system could not
answer what it had spent, even approximately. Every question the phase brief
asks ("how many calls today", "why was Claude used", "which task cost most")
is answered from the `ai_requests` table this module writes.

Recording never breaks a request: `AIGateway._record` swallows failures here
deliberately. Losing an audit row is bad; failing a paid-for AI call because
the audit write failed is worse.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.gateway import UsageRecorder
from ai.schemas import AIRequest, AIResponse
from models.ai_request import AIRequestRecord


class DatabaseUsageRecorder(UsageRecorder):
    """Writes one row per AI request, including blocked and failed ones.

    Blocked requests are recorded precisely because their absence would be
    invisible: a budget that silently refuses work looks identical to a
    system nobody used.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def record(self, request: AIRequest, response: AIResponse) -> None:
        routing = response.routing
        session: Session = self._session_factory()
        try:
            session.add(
                AIRequestRecord(
                    request_id=response.request_id,
                    created_at=request.context.created_at,
                    task_type=str(request.task_type),
                    source=request.context.source,
                    principal=request.context.principal,
                    ticker=request.context.ticker,
                    trigger=request.context.trigger,
                    # Fingerprint, never the prompt itself -- see the model
                    # docstring on why prompt bodies are not persisted.
                    prompt_fingerprint=request.fingerprint(),
                    context_chars=request.context_size,
                    tier=str(routing.tier) if routing else None,
                    provider=response.provider if response.provider != "none" else None,
                    model=response.model if response.model != "none" else None,
                    routing_reason=routing.reason if routing else None,
                    escalated=bool(routing and routing.escalated),
                    escalation_reason=routing.escalation_reason if routing else None,
                    downgraded=bool(routing and routing.downgraded),
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_read_tokens=response.usage.cache_read_tokens,
                    cache_write_tokens=response.usage.cache_write_tokens,
                    estimated_cost=response.cost.amount,
                    cost_currency=response.cost.currency,
                    cost_known=response.cost.known,
                    cost_unknown_reason=response.cost.reason,
                    success=response.success,
                    blocked=response.error_kind
                    in {"budget_exceeded", "rate_limit_exceeded"},
                    error_kind=response.error_kind,
                    error_detail=response.error,
                    finish_reason=str(response.finish_reason),
                    latency_ms=response.latency_ms,
                    retry_count=response.retry_count,
                    cache_hit=response.cached,
                )
            )
            session.commit()
        finally:
            session.close()


# --- aggregation -------------------------------------------------------------


def usage_summary(
    session: Session, *, since: dt.datetime | None = None, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Headline figures for /ai/usage and the dashboard.

    Costs are summed over rows where `cost_known` is true only. Summing
    unknown costs as zero would report a confidently low number -- the same
    mistake as showing an unpriced model as free.
    """
    now = now or dt.datetime.now(dt.UTC)
    since = since or (now - dt.timedelta(days=1))

    rows = session.execute(
        select(
            func.count(AIRequestRecord.id),
            func.sum(AIRequestRecord.input_tokens),
            func.sum(AIRequestRecord.output_tokens),
            func.sum(AIRequestRecord.cache_read_tokens),
        ).where(AIRequestRecord.created_at >= since)
    ).one()

    total_calls = rows[0] or 0
    if total_calls == 0:
        return {
            "recorded": False,
            "reason": "No AI requests have been recorded in this window.",
            "since": since.isoformat(),
        }

    known_cost, unknown_count = session.execute(
        select(
            func.sum(AIRequestRecord.estimated_cost),
            func.count(AIRequestRecord.id).filter(AIRequestRecord.cost_known.is_(False)),
        ).where(AIRequestRecord.created_at >= since)
    ).one()

    succeeded = session.scalar(
        select(func.count(AIRequestRecord.id)).where(
            AIRequestRecord.created_at >= since, AIRequestRecord.success.is_(True)
        )
    )
    blocked = session.scalar(
        select(func.count(AIRequestRecord.id)).where(
            AIRequestRecord.created_at >= since, AIRequestRecord.blocked.is_(True)
        )
    )
    cache_hits = session.scalar(
        select(func.count(AIRequestRecord.id)).where(
            AIRequestRecord.created_at >= since, AIRequestRecord.cache_hit.is_(True)
        )
    )
    escalations = session.scalar(
        select(func.count(AIRequestRecord.id)).where(
            AIRequestRecord.created_at >= since, AIRequestRecord.escalated.is_(True)
        )
    )
    local_calls = session.scalar(
        select(func.count(AIRequestRecord.id)).where(
            AIRequestRecord.created_at >= since, AIRequestRecord.provider == "local"
        )
    )

    return {
        "recorded": True,
        "since": since.isoformat(),
        "calls": total_calls,
        "succeeded": succeeded or 0,
        "failed": total_calls - (succeeded or 0),
        "blocked": blocked or 0,
        "cache_hits": cache_hits or 0,
        "cache_hit_rate": round((cache_hits or 0) / total_calls, 4),
        "escalations": escalations or 0,
        "escalation_rate": round((escalations or 0) / total_calls, 4),
        "local_calls": local_calls or 0,
        "frontier_calls": total_calls - (local_calls or 0),
        "input_tokens": rows[1],
        "output_tokens": rows[2],
        "cache_read_tokens": rows[3],
        "estimated_cost": round(known_cost, 6) if known_cost is not None else None,
        # Stated so a low cost figure is never mistaken for complete.
        "calls_with_unknown_cost": unknown_count or 0,
    }


def usage_by(
    session: Session,
    column: Any,
    *,
    since: dt.datetime | None = None,
    now: dt.datetime | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Group usage by task, model, or provider -- ordered by cost."""
    now = now or dt.datetime.now(dt.UTC)
    since = since or (now - dt.timedelta(days=1))

    rows = session.execute(
        select(
            column,
            func.count(AIRequestRecord.id),
            func.sum(AIRequestRecord.estimated_cost),
            func.sum(AIRequestRecord.input_tokens),
            func.sum(AIRequestRecord.output_tokens),
        )
        .where(AIRequestRecord.created_at >= since)
        .group_by(column)
        .order_by(func.sum(AIRequestRecord.estimated_cost).desc().nullslast())
        .limit(limit)
    ).all()

    return [
        {
            "key": row[0],
            "calls": row[1],
            "estimated_cost": round(row[2], 6) if row[2] is not None else None,
            "input_tokens": row[3],
            "output_tokens": row[4],
        }
        for row in rows
        if row[0] is not None
    ]


def spend_in_window(
    session: Session, *, since: dt.datetime, now: dt.datetime | None = None
) -> float | None:
    """Durable spend for a window, or None when nothing priced was recorded.

    This is the system of record that `/ai/budget` reads. The in-process
    `BudgetLedger` is a fast pre-flight guard; this is the truth.
    """
    total = session.scalar(
        select(func.sum(AIRequestRecord.estimated_cost)).where(
            AIRequestRecord.created_at >= since,
            AIRequestRecord.cost_known.is_(True),
        )
    )
    return round(total, 6) if total is not None else None
