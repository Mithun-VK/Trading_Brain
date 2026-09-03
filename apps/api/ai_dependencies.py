"""FastAPI dependencies for AI-backed routes.

Each factory builds a `GatewayLLMProvider` already labelled with the task,
the calling route, and the authenticated principal. That labelling is what
makes the audit trail answer "why did this call happen" without anyone
having to reconstruct it from logs later (Rules 12 and 13).

Routers depend on these instead of on `get_llm_provider`, so an AI call
cannot reach a provider without passing through gateway policy first.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ai.adapter import GatewayLLMProvider, GatewayUnavailable
from ai.gateway import AIGateway, get_gateway
from ai.schemas import AITaskType, RiskClass
from ai.usage import DatabaseUsageRecorder
from config.settings import get_settings
from integrations.claude.llm_provider import LLMProvider


def get_ai_gateway() -> AIGateway:
    """The process-wide gateway.

    Its usage recorder is attached lazily on first use rather than at import
    time, because the recorder needs a session factory and importing this
    module must not require a database.
    """
    gateway = get_gateway()
    if gateway._recorder is None:  # noqa: SLF001 -- same package, deliberate
        from data.storage.session import get_session_factory

        gateway._recorder = DatabaseUsageRecorder(get_session_factory())  # noqa: SLF001
    return gateway


def _principal(request: Request) -> str | None:
    """Identify the caller for rate-limit keying and the audit row.

    Only a short fingerprint of the bearer token is used, never the token
    itself -- an audit table full of live credentials is a liability, and
    the fingerprint is enough to tell two callers apart.
    """
    import hashlib

    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value:
        return "token:" + hashlib.sha256(value.encode()).hexdigest()[:16]
    client = request.client
    return f"ip:{client.host}" if client else None


def _provider_for(
    task: AITaskType, source: str, risk: RiskClass
):
    def dependency(
        request: Request,
        gateway: AIGateway = Depends(get_ai_gateway),
    ) -> LLMProvider:
        if not get_settings().ai_enabled:
            # A clear 503 rather than a confusing failure deeper in an agent.
            # Deterministic endpoints are unaffected by this.
            raise HTTPException(
                status_code=503,
                detail=(
                    "No AI provider is configured. Set ANTHROPIC_API_KEY or "
                    "LOCAL_LLM_BASE_URL. Deterministic endpoints are unaffected."
                ),
            )
        return GatewayLLMProvider(
            gateway,
            task_type=task,
            source=source,
            principal=_principal(request),
            risk=risk,
        )

    return dependency


# One dependency per AI-capable route, so the task type is fixed by the
# endpoint rather than chosen by a caller. A caller who could pick their own
# task type could pick the cheapest one and defeat routing.
get_research_llm = _provider_for(
    AITaskType.RESEARCH_SYNTHESIS, "api:/research/{ticker}", RiskClass.MEDIUM
)
get_queue_research_llm = _provider_for(
    AITaskType.RESEARCH_SYNTHESIS,
    "api:/research/queue/{id}/process",
    RiskClass.MEDIUM,
)
get_thesis_llm = _provider_for(
    AITaskType.THESIS_REVIEW, "api:/thesis/{ticker}/review", RiskClass.HIGH
)
get_journal_llm = _provider_for(
    AITaskType.JOURNAL_REVIEW, "api:/trades/{id}/review", RiskClass.LOW
)


def ai_unavailable_error(exc: GatewayUnavailable) -> HTTPException:
    """Map a gateway failure to an honest HTTP status.

    The distinctions matter operationally: 429 tells a client to slow down,
    402 says the budget is gone and slowing down will not help, and 503 says
    the provider is down and neither will. Collapsing all three into 500
    would make every one of them look like a bug in TradingBrain.
    """
    status = {
        "rate_limit_exceeded": 429,
        "budget_exceeded": 402,
        "provider_auth": 503,
        "provider_unavailable": 503,
        "rate_limited": 429,
        "no_route": 503,
        "policy_violation": 400,
        "invalid_request": 400,
        "invalid_response": 502,
    }.get(exc.kind, 503)
    return HTTPException(status_code=status, detail=str(exc))
