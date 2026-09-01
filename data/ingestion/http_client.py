"""Shared HTTP plumbing for real (non-mock) market data providers.

Centralizes timeout, retry, and status-code -> ProviderError translation so
each vendor adapter only has to describe its own endpoints and payload
shapes. Transports are injectable so tests never touch the network
(CI must not depend on live market APIs).
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.logging import get_logger
from data.ingestion.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)

logger = get_logger("market_data")

# Yahoo rejects requests without a browser-like UA.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class HttpProviderClient:
    """Thin JSON-over-HTTP client with provider-shaped error handling."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={**_DEFAULT_HEADERS, **(headers or {})},
        )

    def close(self) -> None:
        self._client.close()

    @retry(
        retry=retry_if_exception_type(ProviderUnavailableError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def get_json(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            logger.warning("provider_timeout", operation="GET", status="timeout", path=path)
            raise ProviderUnavailableError(f"Timed out calling {path}") from exc
        except httpx.TransportError as exc:
            logger.warning("provider_connect_error", operation="GET", status="error", path=path)
            raise ProviderUnavailableError(f"Could not connect for {path}: {exc}") from exc

        if response.status_code == 429:
            raise ProviderRateLimitError(f"Rate limited on {path}")
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"Provider rejected the request for {path}")
        if response.status_code == 404:
            raise ProviderNotFoundError(f"No data at {path}")
        if response.status_code >= 500:
            # Server-side faults are transient -- worth a retry/fallback.
            raise ProviderUnavailableError(f"Provider returned {response.status_code} for {path}")
        if response.status_code >= 400:
            raise ProviderDataError(f"Provider returned {response.status_code} for {path}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderDataError(f"Provider returned non-JSON body for {path}") from exc

        if not isinstance(payload, dict):
            raise ProviderDataError(f"Expected a JSON object from {path}")
        return payload


def unwrap_yahoo_number(value: Any) -> float | None:
    """Yahoo returns numbers as either a bare number or {"raw": n, "fmt": "..."}."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("raw")
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
    return None
