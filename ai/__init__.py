"""AI gateway: provider-neutral, cost-aware, deterministic-first.

Application code imports from here rather than from a vendor SDK. See
docs/ai-gateway.md for the architecture and docs/AI_ROUTING_POLICY.md for
which work goes to which tier.
"""

from ai.gateway import AIGateway, get_gateway, reset_gateway
from ai.provider import AIModel, AIProvider, AIProviderRegistry, get_registry
from ai.schemas import (
    AICost,
    AIError,
    AIRequest,
    AIRequestContext,
    AIRequestPolicy,
    AIResponse,
    AIRoutingDecision,
    AITaskType,
    AITier,
    AIUsage,
    LatencyClass,
    PrivacyClass,
    RiskClass,
)

__all__ = [
    "AICost",
    "AIError",
    "AIGateway",
    "AIModel",
    "AIProvider",
    "AIProviderRegistry",
    "AIRequest",
    "AIRequestContext",
    "AIRequestPolicy",
    "AIResponse",
    "AIRoutingDecision",
    "AITaskType",
    "AITier",
    "AIUsage",
    "LatencyClass",
    "PrivacyClass",
    "RiskClass",
    "get_gateway",
    "get_registry",
    "reset_gateway",
]
