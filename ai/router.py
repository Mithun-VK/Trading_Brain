"""Task-based model routing.

Implements docs/AI_ROUTING_POLICY.md. The policy lives in a document as well
as in this code so the two can be checked against each other -- routing code
that is its own only justification cannot be reviewed.

Two rules matter more than the tier table:

1. **A failure never escalates a tier.** If a local model errors, the answer
   is to retry within the tier or fail -- not to hand the same work to the
   most expensive model available. Failure-driven escalation turns an outage
   into a bill.
2. **A privacy constraint outranks output quality.** A `local_only` request
   whose local provider is down fails. It is never escalated.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.provider import AIModel, AIProviderRegistry
from ai.schemas import (
    AIRequest,
    AIRoutingDecision,
    AIRoutingError,
    AITaskType,
    AITier,
    PrivacyClass,
    RiskClass,
)
from config.logging import get_logger

logger = get_logger("ai")


# Base tier per task. Deliberately a closed mapping: a task with no entry is
# a routing bug that must be fixed, never a silent default to the most
# expensive tier.
BASE_TIER: dict[AITaskType, AITier] = {
    AITaskType.SUMMARIZATION: AITier.LOCAL,
    AITaskType.CLASSIFICATION: AITier.LOCAL,
    AITaskType.ENTITY_EXTRACTION: AITier.LOCAL,
    AITaskType.JOURNAL_REVIEW: AITier.LOCAL,
    AITaskType.RESEARCH_SYNTHESIS: AITier.FRONTIER,
    AITaskType.THESIS_REVIEW: AITier.FRONTIER_HIGH,
}

# Tiers ordered cheapest to most capable, for degradation and escalation.
_TIER_ORDER = [AITier.LOCAL, AITier.FRONTIER, AITier.FRONTIER_HIGH]


@dataclass(frozen=True)
class RoutingContext:
    """Live conditions the router must account for, passed in rather than
    read from globals so routing is testable without a running system."""

    budget_degraded: bool = False  # near a budget ceiling; prefer cheaper


class AIRouter:
    def __init__(self, registry: AIProviderRegistry) -> None:
        self._registry = registry

    def route(
        self, request: AIRequest, context: RoutingContext | None = None
    ) -> AIRoutingDecision:
        context = context or RoutingContext()
        policy = request.policy

        base = BASE_TIER.get(request.task_type)
        if base is None:
            raise AIRoutingError(
                f"No routing policy for task {request.task_type!r}. Add one to "
                "BASE_TIER rather than defaulting -- an unrouted task must not "
                "silently reach the most expensive model."
            )

        tier = base
        reason = f"Base tier for {request.task_type} is {base}."
        escalated = False
        escalation_reason: str | None = None
        downgraded = False
        downgrade_reason: str | None = None

        # Escalate on task characteristics, never on failure.
        if policy.allow_escalation:
            escalate_to, why = self._escalation_for(request, tier)
            if escalate_to is not None:
                tier, escalated, escalation_reason = escalate_to, True, why
                reason = f"{reason} Escalated: {why}"

        # Budget pressure degrades, and says so. A silent downgrade would
        # make an expensive question quietly get a cheap answer.
        if context.budget_degraded and tier is not AITier.LOCAL:
            cheaper = _TIER_ORDER[max(0, _TIER_ORDER.index(tier) - 1)]
            if cheaper is not tier:
                tier, downgraded = cheaper, True
                downgrade_reason = "Budget near its ceiling; routed one tier down."
                reason = f"{reason} {downgrade_reason}"

        # Privacy is a hard constraint, applied last so nothing above can
        # undo it.
        if policy.privacy is PrivacyClass.LOCAL_ONLY and tier is not AITier.LOCAL:
            tier = AITier.LOCAL
            downgraded = True
            downgrade_reason = "Request is local_only; frontier tiers are forbidden."
            reason = f"{reason} {downgrade_reason}"

        if not policy.allow_frontier and tier is not AITier.LOCAL:
            tier = AITier.LOCAL
            downgraded = True
            downgrade_reason = "Policy forbids frontier providers for this request."
            reason = f"{reason} {downgrade_reason}"

        model = self._select_model(request, tier)

        decision = AIRoutingDecision(
            tier=tier,
            provider=model.provider,
            model=model.name,
            reason=reason,
            escalated=escalated,
            escalation_reason=escalation_reason,
            downgraded=downgraded,
            downgrade_reason=downgrade_reason,
        )
        logger.info(
            "ai_routed",
            operation="route",
            status="ok",
            request_id=request.context.request_id,
            task=str(request.task_type),
            tier=str(tier),
            provider=model.provider,
            model=model.name,
            escalated=escalated,
        )
        return decision

    # -- internals ------------------------------------------------------------

    def _escalation_for(
        self, request: AIRequest, tier: AITier
    ) -> tuple[AITier | None, str | None]:
        """Task-characteristic escalation only.

        Every reason here is a property of the *question*, never of a failed
        attempt to answer it.
        """
        if tier is AITier.FRONTIER_HIGH:
            return None, None

        if request.has_contradictions and tier is AITier.FRONTIER:
            return (
                AITier.FRONTIER_HIGH,
                "Evidence contains contradictions; resolution needs high reasoning.",
            )
        if request.policy.risk is RiskClass.HIGH and tier is AITier.LOCAL:
            return (
                AITier.FRONTIER,
                "High-risk task: a wrong answer is consequential.",
            )
        if request.estimated_complexity >= COMPLEXITY_ESCALATION_THRESHOLD:
            nxt = _TIER_ORDER[min(len(_TIER_ORDER) - 1, _TIER_ORDER.index(tier) + 1)]
            if nxt is not tier:
                return (
                    nxt,
                    f"Estimated complexity {request.estimated_complexity:.2f} "
                    f"exceeds {COMPLEXITY_ESCALATION_THRESHOLD}.",
                )
        return None, None

    def _select_model(self, request: AIRequest, tier: AITier) -> AIModel:
        if tier is AITier.NONE:
            raise AIRoutingError(
                "TIER_0 tasks must not reach the router: they are deterministic "
                "and must be computed, not asked."
            )

        candidates = self._registry.models_for_tier(tier)
        if not candidates:
            raise AIRoutingError(
                f"No model is available at {tier} for task {request.task_type}. "
                "Configure one, or adjust the request policy -- the gateway will "
                "not substitute a model from another tier."
            )

        allowed = request.policy.allowed_models
        if allowed:
            candidates = [m for m in candidates if m.name in allowed]
            if not candidates:
                raise AIRoutingError(
                    f"No model at {tier} is in the request's allowed_models list."
                )

        # A requested model is a hint, never a bypass: it is honoured only if
        # it is already a legitimate candidate for the routed tier.
        requested = request.policy.requested_model
        if requested:
            for model in candidates:
                if model.name == requested:
                    return model
            logger.info(
                "ai_requested_model_ignored",
                operation="route",
                status="ignored",
                request_id=request.context.request_id,
                requested=requested,
                tier=str(tier),
            )

        fitting = [m for m in candidates if request.context_size <= m.max_context_chars]
        if not fitting:
            raise AIRoutingError(
                f"Request of {request.context_size} characters exceeds the context "
                f"window of every model at {tier}. Assemble a smaller evidence "
                "packet rather than risking a silently truncated answer."
            )
        if request.schema is not None:
            with_tools = [m for m in fitting if m.supports_tools]
            # Local models handle schemas via JSON-mode instead of tools, so
            # a lack of tool support is not disqualifying at that tier.
            if with_tools:
                fitting = with_tools

        return fitting[0]


COMPLEXITY_ESCALATION_THRESHOLD = 0.8
