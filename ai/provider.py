"""Provider interface and registry.

A provider knows how to talk to one vendor and nothing else. It does not
route, does not check budgets, does not retry across providers, and does not
decide whether it should have been called -- all of that belongs to the
gateway, so that no provider can be the place a policy is quietly skipped.

This mirrors `data.ingestion.registry`, which enforces the same shape for
market-data vendors, and it enforces the same central rule: a provider that
generates rather than retrieves may be a deliberate primary, but never an
automatic fallback.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from ai.schemas import AIRequest, AIResponse, AIRoutingError, AITier
from config.logging import get_logger

logger = get_logger("ai")


@dataclass(frozen=True)
class AIModel:
    """One callable model, and the facts routing needs about it."""

    name: str
    provider: str
    tier: AITier
    max_context_chars: int
    supports_tools: bool = True
    supports_caching: bool = False

    def __post_init__(self) -> None:
        if self.tier is AITier.NONE:
            raise AIRoutingError(
                f"Model {self.name!r} cannot be registered at TIER_0: that tier "
                "means no LLM is permitted at all."
            )


class AIProvider(ABC):
    """Vendor adapter. Sync by design -- the gateway owns concurrency."""

    name: str
    is_local: bool = False

    @abstractmethod
    def models(self) -> list[AIModel]:
        """Models this provider can serve right now."""

    @abstractmethod
    def invoke(self, request: AIRequest, model: str) -> AIResponse:
        """Execute one request.

        Must raise `AIProviderUnavailable`, `AIProviderAuthError`, or
        `AIRateLimited` for the corresponding failures rather than returning
        a success-shaped response. Must never fabricate content.
        """

    def health(self) -> tuple[bool, str]:
        """(healthy, detail). Must not raise, and must not bill.

        A health check that costs money per poll is a bad health check, so
        the default is a configuration check only.
        """
        return True, "No probe implemented; configuration assumed valid."


@dataclass
class _Registration:
    name: str
    factory: Callable[[], AIProvider]
    is_local: bool
    instance: AIProvider | None = None


class AIProviderRegistry:
    """Lazily constructs providers and answers 'what can serve this tier'."""

    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}
        self._disabled: set[str] = set()

    # -- registration ---------------------------------------------------------

    def register(
        self, name: str, factory: Callable[[], AIProvider], *, is_local: bool = False
    ) -> None:
        if name in self._registrations:
            raise AIRoutingError(f"Provider {name!r} is already registered")
        self._registrations[name] = _Registration(
            name=name, factory=factory, is_local=is_local
        )

    def available(self) -> list[str]:
        return sorted(n for n in self._registrations if n not in self._disabled)

    def is_registered(self, name: str) -> bool:
        return name in self._registrations

    def is_local(self, name: str) -> bool:
        return self._require(name).is_local

    def disable(self, name: str) -> None:
        """Take a provider out of rotation without unregistering it.

        Used by the deterministic-independence test to prove the system
        works with every provider off, and by operators during an incident.
        """
        self._require(name)
        self._disabled.add(name)

    def enable(self, name: str) -> None:
        self._disabled.discard(name)

    def disable_all(self) -> None:
        self._disabled = set(self._registrations)

    # -- access ---------------------------------------------------------------

    def _require(self, name: str) -> _Registration:
        registration = self._registrations.get(name)
        if registration is None:
            known = ", ".join(sorted(self._registrations)) or "none"
            raise AIRoutingError(f"Unknown AI provider {name!r} (registered: {known})")
        return registration

    def get(self, name: str) -> AIProvider:
        if name in self._disabled:
            raise AIRoutingError(f"Provider {name!r} is disabled")
        registration = self._require(name)
        if registration.instance is None:
            registration.instance = registration.factory()
        return registration.instance

    def models_for_tier(self, tier: AITier) -> list[AIModel]:
        """Every healthy model at a tier, across providers.

        Construction failures are swallowed deliberately: a provider whose
        credentials are missing should make its models unavailable, not take
        down routing for the providers that do work.
        """
        found: list[AIModel] = []
        for name in self.available():
            try:
                provider = self.get(name)
            except Exception as exc:  # noqa: BLE001 -- one bad provider is not fatal
                logger.warning(
                    "ai_provider_unavailable",
                    operation="models_for_tier",
                    provider=name,
                    status="skipped",
                    error=type(exc).__name__,
                )
                continue
            found.extend(m for m in provider.models() if m.tier is tier)
        return found

    def health_report(self) -> list[dict[str, object]]:
        report: list[dict[str, object]] = []
        for name in sorted(self._registrations):
            if name in self._disabled:
                report.append(
                    {"provider": name, "healthy": False, "detail": "Disabled by operator."}
                )
                continue
            try:
                healthy, detail = self.get(name).health()
            except Exception as exc:  # noqa: BLE001 -- health must not raise
                healthy, detail = False, f"{type(exc).__name__}: unavailable"
            report.append({"provider": name, "healthy": healthy, "detail": detail})
        return report


_registry: AIProviderRegistry | None = None


def get_registry() -> AIProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def reset_registry() -> None:
    """Test seam. Never called from application code."""
    global _registry
    _registry = None


def build_default_registry() -> AIProviderRegistry:
    """Register providers from configuration.

    Imports are local so that a missing optional dependency (or an
    unreachable local model) cannot break importing this module -- the
    deterministic core must remain importable with no AI stack at all.
    """
    from config.settings import get_settings

    settings = get_settings()
    registry = AIProviderRegistry()

    if settings.anthropic_api_key:
        from ai.providers.anthropic_provider import AnthropicAIProvider

        registry.register(
            "anthropic", lambda: AnthropicAIProvider(get_settings()), is_local=False
        )

    if settings.local_llm_base_url:
        from ai.providers.local_provider import LocalAIProvider

        registry.register(
            "local", lambda: LocalAIProvider(get_settings()), is_local=True
        )

    return registry
