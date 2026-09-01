"""Provider registry: registration, switching, health checks, and fallback.

Safety property worth stating explicitly: a provider registered as
`synthetic=True` (i.e. MockProvider) is **never** used as an automatic
fallback. Silently answering a request for real market data with generated
numbers would violate Rule 4, so synthetic providers can only ever be
selected deliberately, as the primary.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from config.logging import get_logger
from data.ingestion.errors import ProviderError
from data.ingestion.provider import MarketDataProvider

logger = get_logger("market_data")

T = TypeVar("T")

ProviderFactory = Callable[[], MarketDataProvider]


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    healthy: bool
    checked_at: dt.datetime
    synthetic: bool = False
    error: str | None = None
    latency_ms: float | None = None


@dataclass
class _Registration:
    name: str
    factory: ProviderFactory
    synthetic: bool = False
    instance: MarketDataProvider | None = field(default=None, repr=False)


class ProviderRegistry:
    def __init__(self, primary: str | None = None, fallbacks: Sequence[str] = ()) -> None:
        self._registrations: dict[str, _Registration] = {}
        self._primary = primary
        self._fallbacks: list[str] = list(fallbacks)

    # -- registration ---------------------------------------------------------

    def register(
        self, name: str, factory: ProviderFactory, *, synthetic: bool = False
    ) -> None:
        """Register a provider factory. Instantiation is lazy, so registering a
        provider whose credentials are missing costs nothing until it's used.
        """
        self._registrations[name] = _Registration(name=name, factory=factory, synthetic=synthetic)
        if self._primary is None:
            self._primary = name

    def is_registered(self, name: str) -> bool:
        return name in self._registrations

    def available(self) -> list[str]:
        return sorted(self._registrations)

    def is_synthetic(self, name: str) -> bool:
        return self._require(name).synthetic

    # -- selection ------------------------------------------------------------

    @property
    def primary(self) -> str:
        if self._primary is None:
            raise ProviderError("No market data provider is registered")
        return self._primary

    @property
    def fallbacks(self) -> list[str]:
        return list(self._fallbacks)

    def switch(self, name: str) -> None:
        """Make `name` the primary provider."""
        self._require(name)
        logger.info("provider_switch", operation="switch", status="ok", provider=name)
        self._primary = name

    def set_fallbacks(self, names: Sequence[str]) -> None:
        for name in names:
            registration = self._require(name)
            if registration.synthetic:
                raise ProviderError(
                    f"Refusing to use synthetic provider {name!r} as a fallback -- "
                    "generated data must never stand in for real market data (Rule 4)."
                )
        self._fallbacks = list(names)

    def get(self, name: str | None = None) -> MarketDataProvider:
        """Return (lazily constructing and caching) a provider instance."""
        registration = self._require(name or self.primary)
        if registration.instance is None:
            registration.instance = registration.factory()
        return registration.instance

    # -- resilient execution --------------------------------------------------

    def execute(self, operation: str, call: Callable[[MarketDataProvider], T]) -> T:
        """Run `call` against the primary provider, falling back in order on
        `ProviderError`. Raises the last error if every candidate fails --
        never returns a fabricated result.
        """
        last_error: ProviderError | None = None

        for name in [self.primary, *self._fallbacks]:
            if name != self.primary and self._require(name).synthetic:
                continue  # defense in depth; set_fallbacks already rejects these
            try:
                result = call(self.get(name))
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "provider_failed",
                    operation=operation,
                    status="error",
                    provider=name,
                    error=type(exc).__name__,
                )
                continue
            if name != self.primary:
                logger.info(
                    "provider_fallback_used",
                    operation=operation,
                    status="ok",
                    provider=name,
                )
            return result

        raise last_error or ProviderError(f"No provider could serve {operation!r}")

    # -- health ---------------------------------------------------------------

    def health_check(self, name: str) -> ProviderHealth:
        registration = self._require(name)
        started = dt.datetime.now(dt.UTC)
        try:
            provider = self.get(name)
            probe = getattr(provider, "health_check", None)
            if callable(probe):
                probe()
        except Exception as exc:  # noqa: BLE001 -- a health check must never raise
            return ProviderHealth(
                name=name,
                healthy=False,
                checked_at=started,
                synthetic=registration.synthetic,
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed_ms = (dt.datetime.now(dt.UTC) - started).total_seconds() * 1000
        return ProviderHealth(
            name=name,
            healthy=True,
            checked_at=started,
            synthetic=registration.synthetic,
            latency_ms=round(elapsed_ms, 2),
        )

    def health_check_all(self) -> list[ProviderHealth]:
        return [self.health_check(name) for name in self.available()]

    # -- internals ------------------------------------------------------------

    def _require(self, name: str) -> _Registration:
        registration = self._registrations.get(name)
        if registration is None:
            known = ", ".join(self.available()) or "none"
            raise ProviderError(f"Unknown market data provider {name!r} (registered: {known})")
        return registration
