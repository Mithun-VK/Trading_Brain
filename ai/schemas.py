"""Core types for the AI gateway.

Provider-neutral by design: nothing in this module imports a vendor SDK, and
application code depends on these types rather than on Anthropic's.

Two conventions carried over from the rest of TradingBrain:

- **Unknown is not zero.** A provider that does not report token counts
  yields `None`, never `0` -- a zero-token call and an unmeasured call are
  different facts, and only one of them is free.
- **Invariants are enforced in construction**, not trusted. A request that
  could not be routed auditably cannot be built.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AITier(StrEnum):
    """Where work belongs. See docs/AI_ROUTING_POLICY.md."""

    NONE = "TIER_0_NONE"  # deterministic; no LLM may be invoked
    LOCAL = "TIER_1_LOCAL"
    FRONTIER = "TIER_2_FRONTIER"
    FRONTIER_HIGH = "TIER_3_FRONTIER_HIGH"


class AITaskType(StrEnum):
    """Closed set. A task the router has no policy for is a routing bug, not
    a default-to-most-expensive case."""

    RESEARCH_SYNTHESIS = "research_synthesis"
    THESIS_REVIEW = "thesis_review"
    JOURNAL_REVIEW = "journal_review"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    ENTITY_EXTRACTION = "entity_extraction"


class LatencyClass(StrEnum):
    INTERACTIVE = "interactive"  # a human is waiting
    BACKGROUND = "background"  # may be queued or batched


class PrivacyClass(StrEnum):
    NORMAL = "normal"
    LOCAL_ONLY = "local_only"  # must never leave the machine


class RiskClass(StrEnum):
    """How consequential a wrong answer is. Drives tier, not model quality
    preference."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FinishReason(StrEnum):
    COMPLETE = "complete"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    ERROR = "error"


# --- usage and cost ----------------------------------------------------------


@dataclass(frozen=True)
class AIUsage:
    """Token counts. Every field is optional because not every provider
    reports them, and a missing count must not read as zero."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        parts = [self.input_tokens, self.output_tokens]
        if any(p is None for p in parts):
            return None
        return sum(p for p in parts if p is not None)

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True)
class AICost:
    """An estimate, or an explicit statement that none can be made.

    `known=False` is not an error state -- it is the correct answer when a
    model has no configured price. Reporting 0.0 there would make an
    unpriced model look free, which is the most expensive kind of wrong.
    """

    amount: float | None = None
    currency: str = "USD"
    known: bool = True
    reason: str | None = None

    @classmethod
    def unknown(cls, reason: str) -> AICost:
        return cls(amount=None, known=False, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "known": self.known,
            "reason": self.reason,
        }


# --- requests ----------------------------------------------------------------


@dataclass(frozen=True)
class AIRequestContext:
    """Who/what is asking. Carried through so an audit row can answer 'why
    did this call happen' without joining three tables."""

    request_id: str
    source: str  # e.g. "api:/research/queue/{id}/process"
    principal: str | None = None  # auth identity when one exists
    ticker: str | None = None
    trigger: str | None = None  # what event justified this call
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


@dataclass(frozen=True)
class AIRequestPolicy:
    """Constraints the router must respect. Separate from the request body so
    a policy can be applied without rewriting the payload."""

    latency: LatencyClass = LatencyClass.INTERACTIVE
    privacy: PrivacyClass = PrivacyClass.NORMAL
    risk: RiskClass = RiskClass.MEDIUM
    max_output_tokens: int = 1024
    allow_frontier: bool = True
    allow_escalation: bool = True
    allowed_models: tuple[str, ...] = ()  # empty = policy decides
    requested_model: str | None = None  # a hint, never a bypass
    timeout_seconds: float = 60.0
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.max_output_tokens <= 0:
            raise AIRequestError("max_output_tokens must be positive")
        if self.max_output_tokens > MAX_OUTPUT_TOKENS_CEILING:
            raise AIRequestError(
                f"max_output_tokens {self.max_output_tokens} exceeds the ceiling "
                f"of {MAX_OUTPUT_TOKENS_CEILING}. An unbounded output is an "
                "unbounded bill."
            )
        if self.timeout_seconds <= 0:
            raise AIRequestError("timeout_seconds must be positive")
        if self.max_attempts < 1 or self.max_attempts > MAX_ATTEMPTS_CEILING:
            raise AIRequestError(
                f"max_attempts must be between 1 and {MAX_ATTEMPTS_CEILING}"
            )
        if self.privacy is PrivacyClass.LOCAL_ONLY and self.allow_frontier:
            raise AIRequestError(
                "A local_only request cannot allow frontier providers. The "
                "privacy constraint outranks output quality."
            )


# Hard ceilings. These are not policy defaults that a caller may raise --
# they are the outer bound on what any single request can cost.
MAX_OUTPUT_TOKENS_CEILING = 8192
MAX_INPUT_CHARS_CEILING = 400_000
MAX_ATTEMPTS_CEILING = 3


@dataclass(frozen=True)
class AIRequest:
    """One unit of AI work.

    Carries enough metadata for routing to be auditable after the fact --
    which is the point of Rule 12. A request that cannot say what kind of
    task it is cannot be routed by task, so `task_type` is required.
    """

    task_type: AITaskType
    prompt: str
    context: AIRequestContext
    policy: AIRequestPolicy = field(default_factory=AIRequestPolicy)
    system: str = ""
    schema: dict[str, Any] | None = None  # tool schema for structured extraction
    static_prefix: str = ""  # cacheable; see docs/AI_COST_MODEL.md
    has_contradictions: bool = False  # escalation signal, set by the caller
    estimated_complexity: float = 0.5  # 0..1

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise AIRequestError("An AI request must carry a non-empty prompt")
        if len(self.prompt) + len(self.system) > MAX_INPUT_CHARS_CEILING:
            raise AIRequestError(
                f"Request exceeds the input ceiling of {MAX_INPUT_CHARS_CEILING} "
                "characters. Oversized prompts are a cost-amplification vector; "
                "assemble a smaller evidence packet instead."
            )
        if not 0.0 <= self.estimated_complexity <= 1.0:
            raise AIRequestError("estimated_complexity must be within 0..1")

    @property
    def context_size(self) -> int:
        """Characters, not tokens. Tokens are a provider concern."""
        return len(self.system) + len(self.static_prefix) + len(self.prompt)

    def fingerprint(self) -> str:
        """Deterministic identity for deduplication and caching.

        Includes everything that changes the answer and nothing that does
        not: the request id and timestamp are deliberately excluded, since
        two identical questions asked twice should collide.
        """
        payload = json.dumps(
            {
                "task": str(self.task_type),
                "system": self.system,
                "static_prefix": self.static_prefix,
                "prompt": self.prompt,
                "schema": self.schema,
                "max_output_tokens": self.policy.max_output_tokens,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- routing -----------------------------------------------------------------


@dataclass(frozen=True)
class AIRoutingDecision:
    """Why this request went where it did.

    Rule 12 requires model selection to be auditable, which means the reason
    is part of the decision rather than reconstructed from logs later.
    """

    tier: AITier
    provider: str
    model: str
    reason: str
    escalated: bool = False
    escalation_reason: str | None = None
    downgraded: bool = False
    downgrade_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": str(self.tier),
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "downgraded": self.downgraded,
            "downgrade_reason": self.downgrade_reason,
        }


# --- responses ---------------------------------------------------------------


@dataclass(frozen=True)
class AIResponse:
    """The result of one AI request.

    `success=False` carries a structured reason and never fabricated text --
    a failure that invents a plausible answer is the worst outcome this
    system can produce.
    """

    request_id: str
    success: bool
    provider: str
    model: str
    text: str = ""
    data: dict[str, Any] | None = None  # structured extraction result
    usage: AIUsage = field(default_factory=AIUsage)
    cost: AICost = field(default_factory=lambda: AICost.unknown("not computed"))
    latency_ms: float | None = None
    finish_reason: FinishReason = FinishReason.COMPLETE
    routing: AIRoutingDecision | None = None
    error: str | None = None
    error_kind: str | None = None
    cached: bool = False
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not self.success and (self.text or self.data):
            raise AIResponseError(
                "A failed AI response must not carry content. Returning "
                "invented text on failure is forbidden (see docs/ai-gateway.md)."
            )

    @classmethod
    def unavailable(
        cls,
        request_id: str,
        *,
        reason: str,
        kind: str,
        provider: str = "none",
        model: str = "none",
        routing: AIRoutingDecision | None = None,
        retry_count: int = 0,
    ) -> AIResponse:
        """A structured 'we could not answer'. Callers must handle this
        rather than treating an empty string as an answer."""
        return cls(
            request_id=request_id,
            success=False,
            provider=provider,
            model=model,
            finish_reason=FinishReason.ERROR,
            error=reason,
            error_kind=kind,
            routing=routing,
            retry_count=retry_count,
            cost=AICost.unknown("request did not complete"),
        )

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "finish_reason": str(self.finish_reason),
            "usage": self.usage.to_dict(),
            "cost": self.cost.to_dict(),
            "routing": self.routing.to_dict() if self.routing else None,
            "error_kind": self.error_kind,
            "cached": self.cached,
            "retry_count": self.retry_count,
        }


# --- errors ------------------------------------------------------------------


class AIError(Exception):
    """Base for gateway errors."""

    kind = "ai_error"


class AIRequestError(AIError):
    """The request was malformed or violated a hard ceiling."""

    kind = "invalid_request"


class AIResponseError(AIError):
    """A provider returned something that could not be trusted."""

    kind = "invalid_response"


class AIProviderUnavailable(AIError):
    """A provider could not be reached. Retryable."""

    kind = "provider_unavailable"


class AIProviderAuthError(AIError):
    """Credentials were rejected. Never retryable -- retrying an auth failure
    is pointless and looks like an attack."""

    kind = "provider_auth"


class AIRateLimited(AIError):
    """The provider is throttling us.

    Deliberately its own class rather than folded into 'unavailable': a 429
    means we are asking too fast, and retrying it immediately is the wrong
    response to the request the provider is already refusing.
    """

    kind = "rate_limited"

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AIBudgetExceeded(AIError):
    """A budget window is exhausted."""

    kind = "budget_exceeded"


class AIRateLimitExceeded(AIError):
    """Our own inbound limiter refused the request, before any spend."""

    kind = "rate_limit_exceeded"


class AIRoutingError(AIError):
    """No model satisfies the request's constraints."""

    kind = "no_route"


class AIPolicyViolation(AIError):
    """The request would violate a hard policy, e.g. a Tier 0 task asking
    for an LLM, or a local_only request being escalated."""

    kind = "policy_violation"
