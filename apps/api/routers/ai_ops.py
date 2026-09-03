"""AI operations endpoints.

Read-only and administrative. There is deliberately **no** generic
`POST /ai/raw` or equivalent: an endpoint that accepts an arbitrary prompt
and forwards it to a model is a task-classification bypass, a budget
laundering path, and a prompt-injection surface all at once. AI is reached
only through the task-specific routes that already exist, each with its task
type fixed by the endpoint rather than chosen by the caller.

Nothing here returns a credential, a raw prompt, or a model's full response
body -- only metadata, counts, and cost.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ai.gateway import AIGateway
from ai.usage import spend_in_window, usage_by, usage_summary
from apps.api.ai_dependencies import get_ai_gateway
from apps.api.dependencies import get_session
from models.ai_request import AIRequestRecord

router = APIRouter(tags=["ai"])


@router.get("/ai/status")
def ai_status(gateway: AIGateway = Depends(get_ai_gateway)) -> dict:
    """Provider health, process counters, budgets, and cache state.

    Answers "is AI working right now" without touching the database, so it
    still responds during a database outage.
    """
    return gateway.status()


@router.get("/ai/providers")
def ai_providers(gateway: AIGateway = Depends(get_ai_gateway)) -> dict:
    """Which providers are registered and reachable.

    Names and health only -- never base URLs with embedded credentials, and
    never API keys.
    """
    return {"providers": gateway.registry.health_report()}


@router.get("/ai/routing")
def ai_routing() -> dict:
    """The routing policy currently in force.

    Exposed so the policy can be checked against docs/AI_ROUTING_POLICY.md
    without reading the source -- routing that cannot be inspected cannot be
    audited (Rule 12).
    """
    from ai.router import BASE_TIER, COMPLEXITY_ESCALATION_THRESHOLD

    return {
        "base_tier_by_task": {str(k): str(v) for k, v in BASE_TIER.items()},
        "complexity_escalation_threshold": COMPLEXITY_ESCALATION_THRESHOLD,
        "escalation_rules": [
            "Contradictory evidence escalates research synthesis to high reasoning.",
            "A high-risk task escalates off the local tier.",
            "A failure NEVER escalates a tier -- that would turn an outage "
            "into a bill.",
            "A local_only request is never escalated; the privacy constraint "
            "outranks output quality.",
        ],
    }


@router.get("/ai/usage")
def ai_usage(
    hours: int = Query(default=24, ge=1, le=24 * 90),
    session: Session = Depends(get_session),
) -> dict:
    """Recorded usage over a window.

    Returns `recorded: false` with a reason when nothing has been recorded,
    rather than a row of zeros -- "no AI has run" and "AI ran and cost
    nothing" are different facts.
    """
    now = dt.datetime.now(dt.UTC)
    since = now - dt.timedelta(hours=hours)

    summary = usage_summary(session, since=since, now=now)
    if not summary.get("recorded"):
        return summary

    return {
        **summary,
        "by_task": usage_by(session, AIRequestRecord.task_type, since=since, now=now),
        "by_model": usage_by(session, AIRequestRecord.model, since=since, now=now),
        "by_provider": usage_by(session, AIRequestRecord.provider, since=since, now=now),
    }


@router.get("/ai/budget")
def ai_budget(
    gateway: AIGateway = Depends(get_ai_gateway),
    session: Session = Depends(get_session),
) -> dict:
    """Budget state from both sources, and says which is which.

    The in-process ledger is the fast pre-flight guard; the `ai_requests`
    table is the durable record. They are reported separately rather than
    reconciled, because a discrepancy between them is itself information --
    it means the process restarted, or more than one process is running.
    """
    now = dt.datetime.now(dt.UTC)
    return {
        "windows": gateway.budget.snapshot(now),
        "recorded_spend": {
            "hour": spend_in_window(session, since=now - dt.timedelta(hours=1), now=now),
            "day": spend_in_window(session, since=now - dt.timedelta(days=1), now=now),
            "month": spend_in_window(session, since=now - dt.timedelta(days=30), now=now),
        },
        "note": (
            "'windows' is the in-process pre-flight ledger and resets on "
            "restart. 'recorded_spend' is the durable record from ai_requests "
            "and is authoritative. A null means nothing priced was recorded, "
            "not that nothing was spent."
        ),
    }
