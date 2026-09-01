"""Structured errors for market data providers.

Mirrors the integrations/*/errors.py pattern so every external boundary in
TradingBrain fails the same way: callers catch a domain error, never a raw
`httpx` exception, and transient failures are distinguishable from
permanent ones so retry/fallback logic can be deterministic.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all market data provider errors."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached (connection/timeout). Retryable."""


class ProviderRateLimitError(ProviderUnavailableError):
    """The provider is rate-limiting us. Retryable, and a fallback candidate."""


class ProviderAuthError(ProviderError):
    """The provider rejected our credentials. Not retryable."""


class ProviderDataError(ProviderError):
    """The provider responded, but the payload was missing/unusable.

    Raised rather than returning partial or invented data -- Rule 4: never
    fabricate market data.
    """


class ProviderNotFoundError(ProviderDataError):
    """The provider has no data for the requested symbol."""
