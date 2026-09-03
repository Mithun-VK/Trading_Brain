"""The AI Gateway.

Every runtime AI call in TradingBrain passes through here. Application code
never constructs a provider client, which is asserted by
`tests/ai/test_no_provider_bypass.py` parsing the source tree -- if that rule
were merely documented it would be broken within a month.

Order of operations, and why:

    1. validate            cheapest possible rejection
    2. rate limit          before any database or context work
    3. deduplicate/cache   before paying for an identical answer
    4. route               decide tier and model from the task
    5. budget              projected cost, assuming maximum output
    6. invoke              with a timeout and bounded retries
    7. account and audit   usage, cost, and the routing reason

Each step can end the request more cheaply than the one after it. A limiter
placed after context assembly has already paid for the work it exists to
prevent.

Two things this module will not do:

- **Fabricate.** Every failure path returns a structured
  `AIResponse.unavailable(...)`. There is no code path that invents text
  when a provider is down.
- **Escalate on failure.** A provider error retries within its tier or
  fails. Handing failed work to a more expensive model converts an outage
  into a bill.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ai.governance import (
    TASK_CACHE_TTL,
    BudgetLedger,
    BudgetState,
    RateLimiter,
    ResponseCache,
)
from ai.provider import AIProviderRegistry, get_registry
from ai.router import AIRouter, RoutingContext
from ai.schemas import (
    AIBudgetExceeded,
    AICost,
    AIError,
    AIProviderAuthError,
    AIProviderUnavailable,
    AIRateLimited,
    AIRateLimitExceeded,
    AIRequest,
    AIResponse,
    AIResponseError,
    AITier,
)
from config.ai_pricing import PricingTable
from config.logging import get_logger
from config.settings import Settings, get_settings

logger = get_logger("ai")


@dataclass
class GatewayStats:
    """Process-lifetime counters, for /ai/status.

    The durable record is the ai_requests table; these are a cheap
    always-available summary that survives a database outage.
    """

    requests: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked_rate_limit: int = 0
    blocked_budget: int = 0
    cache_hits: int = 0
    escalations: int = 0
    local_calls: int = 0
    frontier_calls: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "blocked_rate_limit": self.blocked_rate_limit,
            "blocked_budget": self.blocked_budget,
            "cache_hits": self.cache_hits,
            "escalations": self.escalations,
            "local_calls": self.local_calls,
            "frontier_calls": self.frontier_calls,
        }


class AIGateway:
    def __init__(
        self,
        settings: Settings | None = None,
        registry: AIProviderRegistry | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        budget: BudgetLedger | None = None,
        cache: ResponseCache | None = None,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._registry = registry or get_registry()
        self._router = AIRouter(self._registry)
        self._pricing = PricingTable.from_settings(self._settings)
        self._rate_limiter = rate_limiter or RateLimiter(
            per_minute=self._settings.ai_rate_limit_per_minute,
            per_hour=self._settings.ai_rate_limit_per_hour,
        )
        self._budget = budget or BudgetLedger(
            per_request=self._settings.ai_budget_per_request,
            per_hour=self._settings.ai_budget_per_hour,
            per_day=self._settings.ai_budget_per_day,
            per_month=self._settings.ai_budget_per_month,
            warn_ratio=self._settings.ai_budget_warn_ratio,
        )
        self._cache = cache or ResponseCache(
            default_ttl_seconds=self._settings.ai_cache_ttl_seconds
        )
        self._recorder = recorder
        self.stats = GatewayStats()

    # -- public surface -------------------------------------------------------

    @property
    def registry(self) -> AIProviderRegistry:
        return self._registry

    @property
    def budget(self) -> BudgetLedger:
        return self._budget

    @property
    def cache(self) -> ResponseCache:
        return self._cache

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    def invoke(self, request: AIRequest) -> AIResponse:
        """Run one request through the full policy chain.

        Never raises for an expected failure -- callers receive a structured
        `AIResponse` with `success=False` so that a missing AI answer is a
        value they must handle, not an exception that unwinds a request
        handler into a 500.
        """
        self.stats.requests += 1
        started = time.perf_counter()

        try:
            return self._invoke(request, started)
        except AIError as exc:
            return self._fail(request, exc.kind, str(exc), started)
        except Exception as exc:  # noqa: BLE001 -- the gateway must not leak
            logger.warning(
                "ai_gateway_unexpected_error",
                operation="invoke",
                status="error",
                request_id=request.context.request_id,
                error=type(exc).__name__,
            )
            return self._fail(
                request, "internal_error", f"Unexpected {type(exc).__name__}", started
            )

    # -- the chain ------------------------------------------------------------

    def _invoke(self, request: AIRequest, started: float) -> AIResponse:
        # 1. Validate. AIRequest.__post_init__ already enforced the hard
        #    ceilings; this catches the policy-level refusals.
        if not self._settings.ai_enabled:
            raise AIProviderUnavailable(
                "No AI provider is configured. Deterministic features are "
                "unaffected."
            )

        # 2. Rate limit, before touching a provider or assembling anything.
        key = self._rate_key(request)
        verdict = self._rate_limiter.check(key)
        if not verdict.allowed:
            self.stats.blocked_rate_limit += 1
            logger.warning(
                "ai_rate_limited",
                operation="invoke",
                status="blocked",
                request_id=request.context.request_id,
                task=str(request.task_type),
            )
            raise AIRateLimitExceeded(verdict.reason)

        # 3. Cache and in-flight coalescing.
        fingerprint = request.fingerprint()
        cached = self._cache.get(fingerprint)
        if cached is not None:
            self.stats.cache_hits += 1
            logger.info(
                "ai_cache_hit",
                operation="invoke",
                status="ok",
                request_id=request.context.request_id,
                task=str(request.task_type),
            )
            return _as_cached(cached, request.context.request_id)

        if not self._cache.begin(fingerprint):
            raise AIProviderUnavailable(
                "An identical request is already in flight. Retry shortly rather "
                "than paying for the same answer twice."
            )

        try:
            return self._routed_invoke(request, fingerprint, key, started)
        finally:
            self._cache.end(fingerprint)

    def _routed_invoke(
        self, request: AIRequest, fingerprint: str, rate_key: str, started: float
    ) -> AIResponse:
        # 4. Route.
        budget_state = self._budget.check(AICost.unknown("pre-route")).state
        decision = self._router.route(
            request,
            RoutingContext(budget_degraded=budget_state is BudgetState.WARNING),
        )

        # 5. Budget, against a projection that assumes maximum output.
        projected = self._pricing.project(
            decision.model, request.context_size, request.policy.max_output_tokens
        )
        if not projected.known and not self._settings.ai_allow_unpriced_models:
            raise AIBudgetExceeded(
                f"Model {decision.model!r} has no configured price and "
                "AI_ALLOW_UNPRICED_MODELS is false."
            )

        budget_verdict = self._budget.check(projected)
        if not budget_verdict.allowed:
            self.stats.blocked_budget += 1
            logger.warning(
                "ai_budget_blocked",
                operation="invoke",
                status="blocked",
                request_id=request.context.request_id,
                window=budget_verdict.window,
            )
            self._record(request, _blocked_response(request, decision, budget_verdict.reason))
            raise AIBudgetExceeded(budget_verdict.reason)

        # 6. Invoke, with bounded retries inside the chosen tier.
        self._rate_limiter.record(rate_key)
        response = self._call_provider(request, decision)

        # 7. Account and audit.
        response = self._price(response)
        self._budget.record(response.cost)
        self._cache.put(
            fingerprint,
            response,
            ttl_seconds=TASK_CACHE_TTL.get(str(request.task_type)),
        )

        if decision.escalated:
            self.stats.escalations += 1
        if decision.tier is AITier.LOCAL:
            self.stats.local_calls += 1
        else:
            self.stats.frontier_calls += 1
        self.stats.succeeded += 1

        self._record(request, response)
        logger.info(
            "ai_request_completed",
            operation="invoke",
            status="ok",
            request_id=request.context.request_id,
            task=str(request.task_type),
            provider=response.provider,
            model=response.model,
            tier=str(decision.tier),
            latency_ms=response.latency_ms,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    def _call_provider(self, request: AIRequest, decision) -> AIResponse:
        """Invoke, retrying **within the routed tier only**.

        A failure never escalates: handing failed work to a more expensive
        model converts an outage into a bill, and does nothing to fix the
        cause. See docs/AI_ROUTING_POLICY.md.
        """
        provider = self._registry.get(decision.provider)
        attempts = request.policy.max_attempts
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = provider.invoke(request, decision.model)
            except AIProviderAuthError:
                # Never retried. Retrying rejected credentials is pointless
                # and looks like an attack to the provider.
                raise
            except AIRateLimited as exc:
                # Also not retried here. The provider is already refusing us;
                # hammering it is the wrong response, and our own limiter is
                # the correct place to slow down.
                logger.warning(
                    "ai_provider_rate_limited",
                    operation="invoke",
                    status="rate_limited",
                    request_id=request.context.request_id,
                    provider=decision.provider,
                )
                raise exc
            except (AIProviderUnavailable, AIResponseError) as exc:
                last = exc
                logger.warning(
                    "ai_provider_attempt_failed",
                    operation="invoke",
                    status="retry" if attempt < attempts else "failed",
                    request_id=request.context.request_id,
                    provider=decision.provider,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                if attempt < attempts:
                    time.sleep(min(RETRY_BACKOFF_BASE * attempt, RETRY_BACKOFF_MAX))
                continue

            object.__setattr__(response, "routing", decision)
            object.__setattr__(response, "retry_count", attempt - 1)
            return response

        raise last or AIProviderUnavailable("Provider failed with no recorded error")

    # -- helpers --------------------------------------------------------------

    def _price(self, response: AIResponse) -> AIResponse:
        cost = self._pricing.estimate(response.model, response.usage)
        object.__setattr__(response, "cost", cost)
        return response

    def _rate_key(self, request: AIRequest) -> str:
        """Keyed by principal *and* task.

        Per-principal so one caller cannot exhaust another's allowance; per
        task so a burst of cheap classification cannot consume the budget for
        thesis reviews.
        """
        principal = request.context.principal or "anonymous"
        return f"{principal}:{request.task_type}"

    def _fail(
        self, request: AIRequest, kind: str, reason: str, started: float
    ) -> AIResponse:
        self.stats.failed += 1
        response = AIResponse.unavailable(
            request.context.request_id, reason=reason, kind=kind
        )
        object.__setattr__(
            response, "latency_ms", round((time.perf_counter() - started) * 1000, 2)
        )
        self._record(request, response)
        return response

    def _record(self, request: AIRequest, response: AIResponse) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder.record(request, response)
        except Exception as exc:  # noqa: BLE001 -- accounting must never break a request
            logger.warning(
                "ai_usage_record_failed",
                operation="record",
                status="error",
                request_id=request.context.request_id,
                error=type(exc).__name__,
            )

    def status(self) -> dict[str, object]:
        return {
            "enabled": self._settings.ai_enabled,
            "providers": self._registry.health_report(),
            "stats": self.stats.to_dict(),
            "budgets": self._budget.snapshot(),
            "cache": self._cache.stats(),
            "priced_models": self._pricing.priced_models(),
        }


RETRY_BACKOFF_BASE = 0.5
RETRY_BACKOFF_MAX = 4.0


def _as_cached(response: AIResponse, request_id: str) -> AIResponse:
    """Return a cached body under the *current* request's id.

    The cost is zeroed rather than repeated: re-reporting the original price
    would double-count spend that only happened once.
    """
    from dataclasses import replace

    return replace(
        response,
        request_id=request_id,
        cached=True,
        cost=AICost(amount=0.0, known=True),
        latency_ms=0.0,
    )


def _blocked_response(request: AIRequest, decision, reason: str) -> AIResponse:
    response = AIResponse.unavailable(
        request.context.request_id,
        reason=reason,
        kind="budget_exceeded",
        provider=decision.provider,
        model=decision.model,
        routing=decision,
    )
    return response


class UsageRecorder:
    """Persists one audit row per AI request. Implemented in ai/usage.py."""

    def record(self, request: AIRequest, response: AIResponse) -> None:  # pragma: no cover
        raise NotImplementedError


_gateway: AIGateway | None = None


def get_gateway() -> AIGateway:
    global _gateway
    if _gateway is None:
        _gateway = AIGateway()
    return _gateway


def reset_gateway() -> None:
    """Test seam. Never called from application code."""
    global _gateway
    _gateway = None
